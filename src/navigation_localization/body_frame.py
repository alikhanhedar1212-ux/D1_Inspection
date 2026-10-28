from pathlib import Path
from body_geometry import body_pose,body_pose_covariance,load_offset
import math,time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped,PoseStamped
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer,TransformListener
class Body(Node):
 def __init__(self):
  super().__init__('dog_body_frame');self.offset_x,self.offset_y=load_offset(Path(__file__).with_name('body_center_calibration.json'));self.last=None;self.vx=self.vy=self.w=0.;self.buf=Buffer();self.listener=TransformListener(self.buf,self);self.odom=self.create_publisher(Odometry,'/body_odom',10);self.pose=self.create_publisher(PoseStamped,'/body_pose',5);pub=self.create_publisher(TFMessage,'/tf_static',QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL));self.static=pub
  t=TransformStamped();t.header.frame_id='nav_base';t.child_frame_id='nav_body';t.transform.translation.x=self.offset_x;t.transform.translation.y=self.offset_y;t.transform.rotation.z=-math.sqrt(.5);t.transform.rotation.w=math.sqrt(.5);pub.publish(TFMessage(transforms=[t]));self.create_subscription(Odometry,'/odom',self.update,10);self.create_timer(.1,self.show)
 def update(self,m):
  q=m.pose.pose.orientation;yaw=2*math.atan2(q.z,q.w)-math.pi/2;t=m.header.stamp.sec+m.header.stamp.nanosec*1e-9;p=m.pose.pose.position
  base_yaw=2*math.atan2(q.z,q.w)
  m.pose.covariance=body_pose_covariance(m.pose.covariance,base_yaw,self.offset_x,self.offset_y)
  p.x,p.y,yaw=body_pose(p.x,p.y,base_yaw,self.offset_x,self.offset_y)
  if self.last:
   dt=t-self.last[0]
   if .01<dt<.5:
    dx=(p.x-self.last[1])/dt;dy=(p.y-self.last[2])/dt;w=math.atan2(math.sin(yaw-self.last[3]),math.cos(yaw-self.last[3]))/dt;self.vx=.6*self.vx+.4*(math.cos(yaw)*dx+math.sin(yaw)*dy);self.vy=.6*self.vy+.4*(-math.sin(yaw)*dx+math.cos(yaw)*dy);self.w=.6*self.w+.4*w
   else:self.vx=self.vy=self.w=0.
  self.last=(t,p.x,p.y,yaw);m.child_frame_id='nav_body';m.pose.pose.orientation.z=math.sin(yaw/2);m.pose.pose.orientation.w=math.cos(yaw/2);m.twist.twist.linear.x=self.vx;m.twist.twist.linear.y=self.vy;m.twist.twist.angular.z=self.w;self.odom.publish(m)
 def show(self):
  try:
   t=self.buf.lookup_transform('map','nav_body',rclpy.time.Time());m=PoseStamped();m.header=t.header;m.pose.position.x=t.transform.translation.x;m.pose.position.y=t.transform.translation.y;m.pose.orientation=t.transform.rotation;self.pose.publish(m)
  except Exception:pass
rclpy.init();n=Body()
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
