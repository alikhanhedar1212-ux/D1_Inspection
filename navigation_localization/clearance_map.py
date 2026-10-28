import math,time,numpy as np,rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from scipy.ndimage import distance_transform_edt
from tf2_ros import Buffer,TransformListener
class Preference(Node):
 def __init__(self):
  super().__init__('planning_clearance_preference');self.map=None;self.scan=None;self.scan_time=0.;self.buf=Buffer();self.listener=TransformListener(self.buf,self);q=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL);self.pub=self.create_publisher(OccupancyGrid,'/clearance_planning_map',q);self.create_subscription(OccupancyGrid,'/map',self.update,q);self.create_subscription(LaserScan,'/obstacle_scan',self.scans,5);self.create_timer(1.,self.publish)
 def update(self,m):self.map=m;self.base=np.array(m.data,dtype=np.int16).reshape(m.info.height,m.info.width);self.publish()
 def scans(self,m):
  try:t=self.buf.lookup_transform('map',m.header.frame_id,rclpy.time.Time.from_msg(m.header.stamp))
  except Exception:return
  a=np.array(m.ranges);valid=np.isfinite(a);angles=m.angle_min+np.arange(len(a))*m.angle_increment;q=t.transform.rotation;yaw=2*math.atan2(q.z,q.w);self.scan=np.column_stack([a[valid]*np.cos(angles[valid]+yaw)+t.transform.translation.x,a[valid]*np.sin(angles[valid]+yaw)+t.transform.translation.y]);self.scan_time=time.monotonic()
 def publish(self):
  if self.map is None:return
  m=OccupancyGrid();m.header=self.map.header;m.info=self.map.info;a=self.base.copy();i=m.info
  if self.scan is not None and time.monotonic()-self.scan_time<1.:
   ix=np.floor((self.scan[:,0]-i.origin.position.x)/i.resolution).astype(int);iy=np.floor((self.scan[:,1]-i.origin.position.y)/i.resolution).astype(int);good=(ix>=0)&(iy>=0)&(ix<i.width)&(iy<i.height);ix=ix[good];iy=iy[good];known=a[iy,ix]>=0;a[iy[known],ix[known]]=100
  free=a==0;dist=distance_transform_edt(free)*i.resolution;cost=np.rint(90*np.maximum(0.,1.-dist/2.)**2).astype(np.int16);a[free]=cost[free];m.data=a.ravel().astype(np.int8).tolist();self.pub.publish(m)
rclpy.init();n=Preference()
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
