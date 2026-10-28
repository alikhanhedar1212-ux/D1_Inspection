from project_config import remote_file, ssh_command
import time,json,subprocess,math,threading
from pathlib import Path
import numpy as np
from scipy.ndimage import distance_transform_edt
from PIL import Image
import yaml,rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist,PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from terminal_guard import TerminalRotationGuard
from transport_cleanup import close_transport
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Trigger,Empty
from action_msgs.srv import CancelGoal
from action_msgs.msg import GoalStatusArray
from tf2_ros import Buffer,TransformListener
class Bridge(Node):
 def __init__(self):
  super().__init__('rviz_navigation_velocity_bridge');self.command=Twist();self.cmd_time=self.scan_time=0.;self.scan=None;self.confident=False;self.stop=True;self.current_goal=None;self.goal_sources={};self.covariance=None;self.active=False;self.buf=Buffer();self.listener=TransformListener(self.buf,self);self.root=Path(__file__).parent
  control=yaml.safe_load((self.root/'motion.yaml').read_text())['controller_server']['ros__parameters'];limits=control['FollowPath'];self.max_forward=float(limits['max_vel_x'])
  cfg=yaml.safe_load((self.root/'map.yaml').read_text());self.origin=cfg['origin'];self.res=cfg['resolution'];self.map=np.flipud(np.array(Image.open(self.root/cfg['image'])));self.dist=distance_transform_edt(self.map>60)*self.res
  self.goal_not_before=self.get_clock().now().nanoseconds;self.proc=None;self.transport_lost=False;self.next_connect=0.;self.stop_reason='用户停止';self.terminal_guard=TerminalRotationGuard(position_tolerance=float(control['general_goal_checker']['xy_goal_tolerance']),yaw_tolerance=float(control['general_goal_checker']['yaw_goal_tolerance']));self.connect()
  self.create_subscription(Twist,'/nav_cmd_vel',self.cmd,10);self.create_subscription(LaserScan,'/scan',self.scans,5);self.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',self.pose,10);self.create_subscription(GoalStatusArray,'/navigate_to_pose/_action/status',lambda m:self.goals(m,'navigate'),10);self.create_subscription(GoalStatusArray,'/spin/_action/status',lambda m:self.goals(m,'spin'),10);self.create_service(Trigger,'/stop_navigation',self.halt);self.cancel=self.create_client(CancelGoal,'/navigate_to_pose/_action/cancel_goal');self.spin_cancel=self.create_client(CancelGoal,'/spin/_action/cancel_goal');self.create_timer(.05,self.tick);self.body_time=0.;self.stationary_since=None;self.refresh_future=None;self.create_subscription(Odometry,'/body_odom',self.body_motion,10);self.lastreport=0.;self.refresh=self.create_client(Empty,'/request_nomotion_update');self.create_timer(1.,self.refresh_pose)
 def body_motion(self,m):
  stamp=m.header.stamp.sec+m.header.stamp.nanosec*1e-9
  age=self.get_clock().now().nanoseconds*1e-9-stamp
  self.body_time=time.monotonic() if -.05<=age<.7 else 0.
  v=m.twist.twist
  if self.body_time and math.hypot(v.linear.x,v.linear.y)<.03 and abs(v.angular.z)<.05:
   if self.stationary_since is None:self.stationary_since=time.monotonic()
  else:self.stationary_since=None
 def refresh_pose(self):
  # AMCL otherwise stops incorporating scans when the base stops moving.
  # Refresh a poor estimate only with fresh, measured stationary feedback.
  now=time.monotonic()
  stationary=self.stationary_since is not None and now-self.stationary_since>=.6 and now-self.body_time<.7
  pending=self.refresh_future is not None and not self.refresh_future.done()
  if stationary and not self.confident and not pending and self.refresh.service_is_ready():
   self.refresh_future=self.refresh.call_async(Empty.Request())
 def connect(self):
  self.proc=subprocess.Popen(ssh_command('firefly', ['python3', '-u', remote_file('firefly', 'navigation_localization', 'velocity_receiver.py')], ros=True),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
  self.transport_lost=False
  threading.Thread(target=self.feedback,args=(self.proc,),daemon=True).start()
 def feedback(self,proc):
  try:
   for line in proc.stdout:
    if proc is self.proc:
     (self.root/'robot_motion_status.json').write_text(line);print('Firefly:',line.strip(),flush=True)
  except (OSError,ValueError):pass
  finally:
   if proc is self.proc:self.transport_lost=True
 def reconnect(self,now):
  self.stop=True;self.active=False;self.command=Twist();self.cmd_time=0.;self.goal_not_before=self.get_clock().now().nanoseconds
  if self.cancel.service_is_ready():self.cancel.call_async(CancelGoal.Request())
  if self.spin_cancel.service_is_ready():self.spin_cancel.call_async(CancelGoal.Request())
  if now<self.next_connect:return
  self.next_connect=now+2.
  old=self.proc
  close_transport(old)
  self.connect()
 def cmd(self,m):self.command=m;self.cmd_time=time.monotonic()
 def scans(self,m):self.scan=m;self.scan_time=time.monotonic()
 def pose(self,m):
  c=m.pose.covariance;self.covariance=[c[0],c[7],c[35]];self.confident=max(c[0],c[7])<.25 and c[35]<.09
 def goals(self,m,source="navigate"):
  running=[s for s in m.status_list if s.status in (1,2)]
  self.goal_sources[source]=bool(running)
  self.active=any(self.goal_sources.values())
  if running:
   uid=bytes(running[-1].goal_info.goal_id.uuid)
   if uid!=self.current_goal:
    self.current_goal=uid;stamp=running[-1].goal_info.stamp
    if stamp.sec*1000000000+stamp.nanosec>=self.goal_not_before:self.stop=False
 def halt(self,req,res):
  self.goal_not_before=self.get_clock().now().nanoseconds
  self.stop=True;self.active=False;self.command=Twist();self.stop_reason='用户停止';self.terminal_guard.reset()
  if self.cancel.service_is_ready():self.cancel.call_async(CancelGoal.Request())
  if self.spin_cancel.service_is_ready():self.spin_cancel.call_async(CancelGoal.Request())
  res.success=True;res.message='已发送零速度并取消当前导航目标';return res
 def tick(self):
  now=time.monotonic();reason='正常';cmd=Twist();match=0.
  if self.transport_lost or self.proc.poll() is not None:self.reconnect(now)
  try:
   tf=self.buf.lookup_transform('map','nav_scan',rclpy.time.Time());age=self.get_clock().now().nanoseconds*1e-9-tf.header.stamp.sec-tf.header.stamp.nanosec*1e-9
   if self.scan is not None:
    ranges=np.array(self.scan.ranges);valid=np.isfinite(ranges);angles=self.scan.angle_min+np.arange(len(ranges))*self.scan.angle_increment;q=tf.transform.rotation;yaw=2*math.atan2(q.z,q.w);x=ranges[valid]*np.cos(angles[valid]+yaw)+tf.transform.translation.x;y=ranges[valid]*np.sin(angles[valid]+yaw)+tf.transform.translation.y;ix=np.floor((x-self.origin[0])/self.res).astype(int);iy=np.floor((y-self.origin[1])/self.res).astype(int);good=(ix>=0)&(iy>=0)&(ix<self.map.shape[1])&(iy<self.map.shape[0]);match=float(np.count_nonzero(self.dist[iy[good],ix[good]]<.25)/max(1,len(ix)))
   if self.stop:reason=self.stop_reason
   elif not self.active:reason='没有执行中的导航目标'
   elif now-self.cmd_time>.3:reason='导航速度超时'
   elif now-self.scan_time>.7 or age>.7:reason='雷达或定位数据超时'
   elif not self.confident or match<.45:reason='定位质量不足'
   else:
    cmd=self.command
  except Exception:reason='等待实时定位'
  if self.current_goal is not None:
   try:
    alignment=json.loads((self.root/'goal_alignment_status.json').read_text())
    if alignment.get('goal_id')==self.current_goal.hex() and 0<=time.time()-alignment['updated']<.7:
     failure=self.terminal_guard.update(self.current_goal.hex(),alignment['distance_m'],math.radians(alignment['yaw_error_deg']),cmd.linear.x,cmd.angular.z,now)
     if failure:
      (self.root/'terminal_rotation_failure.json').write_text(json.dumps(dict(alignment,reason=failure,stopped=time.time()),ensure_ascii=False))
      self.stop=True;self.active=False;self.stop_reason=failure;self.command=Twist();cmd=Twist();reason=failure
      if self.cancel.service_is_ready():self.cancel.call_async(CancelGoal.Request())
      if self.spin_cancel.service_is_ready():self.spin_cancel.call_async(CancelGoal.Request())
   except (OSError,ValueError,KeyError):pass
  packet={'sent':time.monotonic(),'x':max(-self.max_forward,min(self.max_forward,cmd.linear.x)),'y':0.,'w':max(-.35,min(.35,cmd.angular.z)),'reason':reason,'goal_id':self.current_goal.hex() if self.active and self.current_goal is not None else None}
  try:self.proc.stdin.write(json.dumps(packet)+'\n');self.proc.stdin.flush()
  except (BrokenPipeError,OSError,ValueError):
   self.transport_lost=True;self.stop=True;self.active=False;self.command=Twist();packet.update(x=0.,y=0.,w=0.,goal_id=None,reason='运动连接断开')
  if now-self.lastreport>1.:
   status_path=self.root/'velocity_bridge_status.json'
   temporary=status_path.with_suffix('.tmp')
   temporary.write_text(json.dumps(dict(packet,match=match,covariance=self.covariance,updated=time.time()),ensure_ascii=False))
   temporary.replace(status_path)
   self.lastreport=now
rclpy.init();n=Bridge()
try:rclpy.spin(n)
finally:
 close_transport(n.proc)
 n.destroy_node();rclpy.try_shutdown()
