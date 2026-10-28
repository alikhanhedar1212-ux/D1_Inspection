import math
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import OccupancyGrid
from tf2_ros import Buffer,TransformListener
class Filter(Node):
 def __init__(self):
  super().__init__('navigation_interior_scan');self.grid=None;self.buf=Buffer();self.listener=TransformListener(self.buf,self);self.pub=self.create_publisher(LaserScan,'/obstacle_scan',5);self.create_subscription(OccupancyGrid,'/map',self.map,QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL));self.create_subscription(LaserScan,'/scan',self.scan,5)
 def map(self,m):self.grid=m;self.data=np.array(m.data).reshape(m.info.height,m.info.width)
 def scan(self,m):
  if self.grid is None:return
  try:t=self.buf.lookup_transform('map',m.header.frame_id,rclpy.time.Time.from_msg(m.header.stamp))
  except Exception:return
  a=np.array(m.ranges);valid=np.isfinite(a);angles=m.angle_min+np.arange(len(a))*m.angle_increment;q=t.transform.rotation;yaw=2*math.atan2(q.z,q.w);ids=np.flatnonzero(valid);x=a[valid]*np.cos(angles[valid]+yaw)+t.transform.translation.x;y=a[valid]*np.sin(angles[valid]+yaw)+t.transform.translation.y;i=self.grid.info;ix=np.floor((x-i.origin.position.x)/i.resolution).astype(int);iy=np.floor((y-i.origin.position.y)/i.resolution).astype(int);inside=(ix>=0)&(iy>=0)&(ix<i.width)&(iy<i.height);keep=np.zeros(len(ids),bool);keep[inside]=self.data[iy[inside],ix[inside]]>=0;a[ids[~keep]]=np.nan;m.ranges=a.tolist();self.pub.publish(m)
rclpy.init();n=Filter()
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
