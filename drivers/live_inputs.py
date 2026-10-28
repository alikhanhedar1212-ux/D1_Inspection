from pathlib import Path
from collections import deque
import numpy as np,struct,json,time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from pacecat_m300_inter.msg import CustomMsg as RawCloud
from livox_ros_driver2.msg import CustomMsg as LioCloud
from sensor_msgs.msg import Imu,LaserScan,PointCloud2,PointField
from nav_msgs.msg import Odometry
from scipy.spatial.transform import Rotation
from builtin_interfaces.msg import Time
from self_return_filter import chassis_returns
POINT=np.dtype({'names':['offset','x','y','z','tag'],'formats':['<u4','<f4','<f4','<f4','u1'],'offsets':[0,4,8,12,17],'itemsize':19})
def decode(data):
 sec,nsec,flen=struct.unpack_from('<iII',data,4);pos=16+flen;pos=4+((pos-4+7)//8)*8;tb,count=struct.unpack_from('<QI',data,pos);pos+=16;n=struct.unpack_from('<I',data,pos)[0];pos+=4
 if n!=count:raise ValueError('雷达点数不一致')
 a=np.ndarray((n,),dtype=POINT,buffer=data,offset=pos,strides=(20,));return tb*1e-9,np.column_stack((a['x'],a['y'],a['z'],a['offset'],a['tag']))
def stamp(t):return Time(sec=int(t),nanosec=int((t-int(t))*1e9))
def cloud_message(t,points):
 m=PointCloud2();m.header.stamp=stamp(t);m.header.frame_id='nav_scan';m.height=1;m.width=len(points);m.fields=[PointField(name=name,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,name in enumerate(('x','y','z'))];m.is_bigendian=False;m.point_step=12;m.row_step=m.width*12;m.is_dense=True;m.data=np.asarray(points,dtype='<f4').tobytes();return m
class Inputs(Node):
 def __init__(self):
  super().__init__('navigation_live_inputs');self.ext=np.array([[0,1,0],[-1,0,0],[0,0,1]]);self.T=np.array([.0178,-.0049,-.0383]);self.acc=[];self.level=None;self.pose=deque(maxlen=100);self.scans=deque(maxlen=5);self.count=0;self.start=time.monotonic();self.last_report=0;self.ground=-.37128
  self.lidar_pub=self.create_publisher(LioCloud,'/nav/lidar',10);self.imu_pub=self.create_publisher(Imu,'/nav/imu',50);self.scan_pub=self.create_publisher(LaserScan,'/nav/scan',2);self.odom_pub=self.create_publisher(Odometry,'/nav/odom',5)
  self.mark_pub=self.create_publisher(PointCloud2,'/nav/obstacle_points',2);self.clear_pub=self.create_publisher(PointCloud2,'/nav/clearing_points',2)
  self.create_subscription(RawCloud,'/custommsg',self.cloud,1,raw=True);self.create_subscription(Imu,'/m300_imu',self.imu,qos_profile_sensor_data);self.create_subscription(Odometry,'/nav/raw_odom',self.odometry,10)
 def imu(self,m):
  self.imu_pub.publish(m)
  if self.level is None:
   a=m.linear_acceleration;self.acc.append([a.x,a.y,a.z])
   if len(self.acc)>=200:
    g=np.mean(self.acc,axis=0);g/=np.linalg.norm(g);v=np.cross(g,[0,0,1]);K=np.array([[0,-v[2],v[1]],[v[2],0,-v[0]],[-v[1],v[0],0]]);self.level=np.eye(3)+K+K@K/(1+g[2]);self.get_logger().info('已完成 IMU 重力校平')
 def cloud(self,data):
  # Both message definitions have identical fields; preserve device timestamps exactly.
  self.lidar_pub.publish(data)
  t,raw=decode(data);self.scans.append((t,raw));self.process()
 def odometry(self,m):
  if self.level is None:return
  p=m.pose.pose.position;q=m.pose.pose.orientation;t=m.header.stamp.sec+m.header.stamp.nanosec*1e-9
  self.pose.append([t,p.x,p.y,p.z,q.x,q.y,q.z,q.w]);R=self.level@Rotation.from_quat([q.x,q.y,q.z,q.w]).as_matrix();yaw=np.arctan2(R[1,0],R[0,0]);pos=self.level@np.array([p.x,p.y,p.z]);out=Odometry();out.header.stamp=m.header.stamp;out.header.frame_id='nav_odom';out.child_frame_id='nav_base';out.pose.pose.position.x=float(pos[0]);out.pose.pose.position.y=float(pos[1]);out.pose.pose.orientation.z=float(np.sin(yaw/2));out.pose.pose.orientation.w=float(np.cos(yaw/2));out.pose.covariance[0]=.01;out.pose.covariance[7]=.01;out.pose.covariance[35]=.01;self.odom_pub.publish(out);self.process()
 def process(self):
  if self.level is None or len(self.pose)<2:return
  poses=np.array(self.pose)
  while self.scans:
   t,raw=self.scans[0];end=t+float(raw[:,3].max())*1e-9
   if poses[-1,0]<end:break
   self.scans.popleft()
   if t<poses[0,0]:continue
   self.count+=1
   if self.count%2:continue
   valid=np.isfinite(raw[:,:3]).all(axis=1)&(np.linalg.norm(raw[:,:3],axis=1)>.4)&(raw[:,4]==0);raw=raw[valid];pt=t+raw[:,3]*1e-9;center=(t+end)/2
   vals=np.column_stack([np.interp(pt,poses[:,0],poses[:,j]) for j in range(1,8)]);q=vals[:,3:];q/=np.linalg.norm(q,axis=1)[:,None];pc=np.array([np.interp(center,poses[:,0],poses[:,j]) for j in range(1,8)]);qc=pc[3:]/np.linalg.norm(pc[3:]);R=self.level@Rotation.from_quat(qc).as_matrix();yaw=np.arctan2(R[1,0],R[0,0]);world=Rotation.from_quat(q).apply(raw[:,:3]@self.ext.T+self.T)+vals[:,:3];relative=world@self.level.T-pc[:3]@self.level.T;local=relative@np.array([[np.cos(yaw),-np.sin(yaw),0],[np.sin(yaw),np.cos(yaw),0],[0,0,1]])
   dist=np.linalg.norm(local[:,:2],axis=1);floor=self.ground;near=(dist>.5)&(dist<5)&(local[:,2]>floor-.4)&(local[:,2]<floor+.3);z=local[near,2]
   if len(z)>100:
    hist,edges=np.histogram(z,bins=np.arange(floor-.4,floor+.32,.02));i=hist.argmax()
    if hist[i]>20:floor=float((edges[i]+edges[i+1])*.5)
   height=local[:,2]-floor;candidate=(height>=.2)&(height<=1.4)&(dist>=.5)&(dist<=20);self_hits=chassis_returns(local);good=candidate&~self_hits;angles=np.arctan2(local[good,1],local[good,0]);ids=np.clip(np.floor((angles+np.pi)/(np.pi/360)).astype(int),0,719);ranges=np.full(720,np.inf,np.float32);np.minimum.at(ranges,ids,dist[good]);ranges[~np.isfinite(ranges)]=np.nan
   scan=LaserScan();scan.header.stamp=stamp(center);scan.header.frame_id='nav_scan';scan.angle_min=-np.pi;scan.angle_increment=np.pi/360;scan.angle_max=scan.angle_min+719*scan.angle_increment;scan.scan_time=.2;scan.range_min=.5;scan.range_max=20.;scan.ranges=ranges.tolist();self.scan_pub.publish(scan)
   self.mark_pub.publish(cloud_message(center,local[good]));clear=(dist>=.5)&(dist<=20)&~self_hits;self.clear_pub.publish(cloud_message(center,local[clear]))
   if time.monotonic()-self.last_report>5:
    report={'scan_count':self.count//2,'valid_beams':int(np.isfinite(ranges).sum()),'self_returns_removed':int((candidate&self_hits).sum()),'floor_m':floor,'odom_xy':pc[:2].tolist(),'device_time':center,'host_time':time.time()};Path(__file__).with_name('input_status.json').write_text(json.dumps(report));self.get_logger().info(str(report));self.last_report=time.monotonic()
rclpy.init();n=Inputs()
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
