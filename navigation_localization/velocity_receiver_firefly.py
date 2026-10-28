import sys,json,time,threading,math
from pathlib import Path
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from robots_dog_msgs.msg import McModeCmd,McState
class Receiver(Node):
 def __init__(self):
  super().__init__('rviz_navigation_velocity_receiver');self.pub=self.create_publisher(Twist,'/cmd_vel',10);self.modepub=self.create_publisher(McModeCmd,'/arc/mc_mode_cmd',10);self.state=None;self.state_time=0.;self.latest=None;self.base=None;self.lock=threading.Lock();self.requested=False;self.active=False;self.closed=False;self.last_report=0.;self.count=0;self.create_subscription(McState,'/arc/mc_state',self.status,10);self.create_timer(.05,self.tick);threading.Thread(target=self.read,daemon=True).start()
 def status(self,m):self.state=m.state;self.state_time=time.monotonic()
 def read(self):
  try:
   for line in sys.stdin:
    p=json.loads(line)
    if p.get('shutdown'):break
    now=time.monotonic()
    with self.lock:
     if self.base is None:self.base=(p['sent'],now)
     self.latest=p
  finally:self.closed=True
 def tick(self):
  now=time.monotonic();m=Twist();reason='等待目标';p=self.latest
  fresh=p is not None and now-(self.base[1]+p['sent']-self.base[0])<.35 and not self.closed
  if fresh:
   goal=p.get('goal_id')
   if goal is not None and goal!=getattr(self,'goal_id',None):self.goal_id=goal;self.requested=False
   x=float(p['x']);y=float(p['y']);w=float(p['w'])
   if not all(math.isfinite(v) for v in (x,y,w)):x=y=w=0.
   x=max(-.15,min(.30,x));y=0.;w=max(-.35,min(.35,w));moving=abs(x)+abs(y)+abs(w)>1e-5
   if moving and not self.requested and self.state==McState.STATE_STANDBY and now-self.state_time<1.:
    mode=McModeCmd();mode.stamp=self.get_clock().now().to_msg();mode.mode=McModeCmd.NAV_VEL_CTRL;self.modepub.publish(mode);self.requested=True;self.get_logger().info('目标已下发，切换导航速度模式')
   if moving and self.state==McState.STATE_NAV_VEL_CTRL and now-self.state_time<1.:
    m.linear.x=x;m.linear.y=y;m.angular.z=w;self.active=True;reason='导航速度已转发'
   elif moving:reason='底层模式未允许导航速度'
   else:reason=p.get('reason','零速度')
  else:reason='控制数据超时，停止'
  state_fresh=now-self.state_time<1.
  if state_fresh and self.state!=McState.STATE_NAV_VEL_CTRL:self.active=False
  if self.active or (fresh and state_fresh and self.state==McState.STATE_NAV_VEL_CTRL):self.pub.publish(m);self.count+=1
  if now-self.last_report>1.:
   info={'state':self.state,'reason':reason,'cmd':[m.linear.x,m.linear.y,m.angular.z],'published':self.count,'wall_time':time.time()};Path(__file__).with_name('motion_status.json').write_text(json.dumps(info,ensure_ascii=False));print(json.dumps(info,ensure_ascii=False),flush=True);self.last_report=now
  if self.closed:
   if self.active and self.state==McState.STATE_NAV_VEL_CTRL:self.pub.publish(Twist())
   rclpy.shutdown()
rclpy.init();n=Receiver()
try:rclpy.spin(n)
finally:
 if n.active and n.state==McState.STATE_NAV_VEL_CTRL:n.pub.publish(Twist())
 n.destroy_node();rclpy.try_shutdown()
