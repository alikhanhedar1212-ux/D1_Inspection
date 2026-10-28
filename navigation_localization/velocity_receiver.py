"""Firefly single-owner velocity receiver. A stale stream stops and exits."""
import sys,json,time,threading,math,signal,os
from pathlib import Path
from receiver_guard import ReceiverLock,InputWatchdog,LatestTelemetry
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from robots_dog_msgs.msg import McModeCmd,McState

class Receiver(Node):
    def __init__(self):
        super().__init__('rviz_navigation_velocity_receiver')
        self.pub=self.create_publisher(Twist,'/cmd_vel',1)
        self.modepub=self.create_publisher(McModeCmd,'/arc/mc_mode_cmd',10)
        self.state=None;self.state_time=0.;self.latest=None;self.lock=threading.Lock()
        self.watchdog=InputWatchdog(time.monotonic());self.requested=False;self.active=False
        self.closed=False;self.last_report=0.;self.count=0;self.feedback=LatestTelemetry()
        self.create_subscription(McState,'/arc/mc_state',self.status,10)
        self.create_timer(.05,self.tick)
        threading.Thread(target=self.read,daemon=True).start()
        threading.Thread(target=self.report,daemon=True).start()
    def status(self,m):self.state=m.state;self.state_time=time.monotonic()
    def read(self):
        try:
            for line in sys.stdin:
                p=json.loads(line)
                if p.get('shutdown'):break
                now=time.monotonic()
                with self.lock:self.watchdog.receive(float(p['sent']),now);self.latest=p
        except (OSError,ValueError,KeyError,TypeError):pass
        finally:self.closed=True
    def report(self):
        # A disconnected or full SSH output pipe must never block the control timer.
        try:
            while not self.closed:
                try:info=self.feedback.queue.get(timeout=.2)
                except __import__('queue').Empty:continue
                print(json.dumps(info,ensure_ascii=False),flush=True)
        except (BrokenPipeError,OSError):self.closed=True
    def tick(self):
        now=time.monotonic();m=Twist();reason='等待目标'
        with self.lock:p=self.latest;fresh=self.watchdog.fresh(now);expired=self.watchdog.expired(now)
        state_fresh=now-self.state_time<1.
        if fresh and not self.closed:
            goal=p.get('goal_id')
            if goal is not None and goal!=getattr(self,'goal_id',None):self.goal_id=goal;self.requested=False
            x=float(p['x']);y=float(p['y']);w=float(p['w'])
            if not all(math.isfinite(v) for v in (x,y,w)):x=y=w=0.
            x=max(-.15,min(.30,x));y=0.;w=max(-.35,min(.35,w));moving=abs(x)+abs(w)>1e-5
            if moving and not self.requested and self.state==McState.STATE_STANDBY and state_fresh:
                mode=McModeCmd();mode.stamp=self.get_clock().now().to_msg();mode.mode=McModeCmd.NAV_VEL_CTRL
                self.modepub.publish(mode);self.requested=True
            if moving and self.state==McState.STATE_NAV_VEL_CTRL and state_fresh:
                m.linear.x=x;m.angular.z=w;self.active=True;reason='导航速度已转发'
            elif moving:reason='底层模式未允许导航速度'
            else:reason=p.get('reason','零速度')
        else:reason='控制数据超时，停止'
        if state_fresh and self.state!=McState.STATE_NAV_VEL_CTRL:self.active=False
        if self.active or (fresh and state_fresh and self.state==McState.STATE_NAV_VEL_CTRL):
            self.pub.publish(m);self.count+=1
        if now-self.last_report>1.:
            info={'state':self.state,'reason':reason,'cmd':[m.linear.x,m.linear.y,m.angular.z],'published':self.count,'wall_time':time.time(),'pid':__import__('os').getpid()}
            path=Path(__file__).with_name('motion_status.json');tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(info,ensure_ascii=False));tmp.replace(path)
            self.feedback.put(info);self.last_report=now
        if self.closed or expired:
            if self.state==McState.STATE_NAV_VEL_CTRL:self.pub.publish(Twist())
            self.closed=True

def main():
    owner=ReceiverLock(Path(__file__).with_suffix('.lock')).acquire()
    rclpy.init();n=Receiver()
    signal.signal(signal.SIGTERM,lambda *_:setattr(n,'closed',True))
    try:
        while rclpy.ok() and not n.closed:rclpy.spin_once(n,timeout_sec=.05)
    finally:
        # Shut ROS down outside its callback, with a bounded exit if middleware hangs.
        timer=threading.Timer(2.,lambda:os._exit(0));timer.daemon=True;timer.start()
        n.closed=True
        if rclpy.ok() and n.active and n.state==McState.STATE_NAV_VEL_CTRL:n.pub.publish(Twist())
        try:n.destroy_node();rclpy.try_shutdown()
        finally:owner.close();timer.cancel()

if __name__=='__main__':main()
