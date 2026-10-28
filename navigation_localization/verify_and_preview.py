from pathlib import Path
import rclpy,time,math,json,yaml,numpy as np
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
from rclpy.action import ActionClient
from geometry_msgs.msg import PoseWithCovarianceStamped,PoseStamped
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Path as RosPath
from nav2_msgs.action import ComputePathToPose
from std_srvs.srv import Empty
from PIL import Image
from scipy import ndimage
root=Path(__file__).parent;rclpy.init();n=rclpy.create_node('verify_localization_and_preview');poses=[];last_scan=[None]
def pose_cb(m):poses.append(m)
n.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',pose_cb,QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL));n.create_subscription(LaserScan,'/scan',lambda m:last_scan.__setitem__(0,m),10);client=n.create_client(Empty,'/request_nomotion_update')
if not client.wait_for_service(timeout_sec=10):raise RuntimeError('AMCL 更新服务不可用')
for i in range(10):
 f=client.call_async(Empty.Request());rclpy.spin_until_future_complete(n,f,timeout_sec=2)
 until=time.monotonic()+.7
 while time.monotonic()<until:rclpy.spin_once(n,timeout_sec=.1)
if not poses or last_scan[0] is None:raise RuntimeError('未收到实时定位或扫描')
p=poses[-1];pos=p.pose.pose.position;q=p.pose.pose.orientation;yaw=math.atan2(2*q.w*q.z,1-2*q.z*q.z);cov=p.pose.covariance
m=yaml.safe_load((root/'map.yaml').read_text());g=np.flipud(np.asarray(Image.open(root/'map.pgm')));field=ndimage.distance_transform_edt(g>=50)*m['resolution'];scan=last_scan[0];rr=np.array(scan.ranges);aa=scan.angle_min+np.arange(len(rr))*scan.angle_increment+yaw;valid=np.isfinite(rr)&(rr>.6)&(rr<15);points=np.column_stack((pos.x+rr[valid]*np.cos(aa[valid]),pos.y+rr[valid]*np.sin(aa[valid])));cells=np.floor((points-np.array(m['origin'][:2]))/m['resolution']).astype(int);inside=(cells[:,0]>=0)&(cells[:,0]<g.shape[1])&(cells[:,1]>=0)&(cells[:,1]<g.shape[0]);dist=field[cells[inside,1],cells[inside,0]];report={'initialization':'automatic scan-to-map candidate, physical position not yet confirmed','amcl_pose':{'x':pos.x,'y':pos.y,'yaw':yaw,'std_x_m':math.sqrt(max(cov[0],0)),'std_y_m':math.sqrt(max(cov[7],0)),'std_yaw_rad':math.sqrt(max(cov[35],0))},'scan_endpoints_within_20cm_of_obstacle_fraction':float((dist<.2).sum()/valid.sum()),'scan_observed_beams':int(valid.sum()),'stationary_pose_updates':len(poses),'plans':[]}
planner=ActionClient(n,ComputePathToPose,'/compute_path_to_pose');assert planner.wait_for_server(timeout_sec=10);pub=n.create_publisher(RosPath,'/preview_path',QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE));preview=None
for w in yaml.safe_load((root/'waypoints.yaml').read_text())['waypoints']:
 goal=ComputePathToPose.Goal();goal.goal.header.frame_id='map';goal.goal.header.stamp=n.get_clock().now().to_msg();goal.goal.pose.position.x=w['x'];goal.goal.pose.position.y=w['y'];goal.goal.pose.orientation.z=math.sin(w['yaw']/2);goal.goal.pose.orientation.w=math.cos(w['yaw']/2);goal.planner_id='GridBased';goal.use_start=False
 f=planner.send_goal_async(goal);rclpy.spin_until_future_complete(n,f,timeout_sec=10)
 if not f.done():raise RuntimeError('规划请求超时')
 handle=f.result();item={'id':w['id'],'name':w['name'],'goal_xy':[w['x'],w['y']],'waypoint_confirmed':False}
 if not handle.accepted:item['status']='rejected';report['plans'].append(item);continue
 f=handle.get_result_async();rclpy.spin_until_future_complete(n,f,timeout_sec=20)
 if not f.done():raise RuntimeError('规划结果超时')
 result=f.result();path=result.result.path;item['status']=int(result.status);item['path_poses']=len(path.poses)
 if path.poses:
  a=np.array([[v.pose.position.x,v.pose.position.y] for v in path.poses]);item['length_m']=float(np.linalg.norm(np.diff(a,axis=0),axis=1).sum());np.save(root/f'path_{w["id"]}.npy',a)
  if w['id']==1:preview=path;pub.publish(path)
 report['plans'].append(item)
 print(item,flush=True)
(root/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
if preview:
 while rclpy.ok():rclpy.spin_once(n,timeout_sec=.5)
else:n.destroy_node();rclpy.try_shutdown()
