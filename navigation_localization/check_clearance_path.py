from pathlib import Path
import sys,json,numpy as np,yaml,rclpy
from PIL import Image
from scipy.ndimage import distance_transform_edt
from rclpy.action import ActionClient
from nav2_msgs.action import ComputePathToPose
from nav_msgs.msg import Path as RosPath
from rclpy.qos import QoSProfile,DurabilityPolicy
r=Path(__file__).parent;tag=sys.argv[1];rclpy.init();n=rclpy.create_node('clearance_path_check');c=ActionClient(n,ComputePathToPose,'/compute_path_to_pose');assert c.wait_for_server(timeout_sec=8);g=ComputePathToPose.Goal();g.goal.header.frame_id='map';w=yaml.safe_load((r/'waypoints.yaml').read_text())['waypoints'][5];g.goal.pose.position.x=w['x'];g.goal.pose.position.y=w['y'];g.goal.pose.orientation.w=1.;g.planner_id='GridBased';f=c.send_goal_async(g);rclpy.spin_until_future_complete(n,f,timeout_sec=15);h=f.result();assert h.accepted;f=h.get_result_async();rclpy.spin_until_future_complete(n,f,timeout_sec=15);result=f.result();assert result.status==4
xy=np.array([[p.pose.position.x,p.pose.position.y] for p in result.result.path.poses]);a=np.flipud(np.array(Image.open(r/'map.pgm')));d=distance_transform_edt(a==254)*.05;ix=((xy[:,0]+31.5)/.05).astype(int);iy=((xy[:,1]+21.9)/.05).astype(int);values=d[iy,ix];info={'status':4,'min_center_clearance_m':float(values.min()),'clearance_p10_m':float(np.percentile(values,10)),'length_m':float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum())};(r/f'clearance_{tag}.json').write_text(json.dumps(info,indent=2));np.save(r/f'clearance_{tag}.npy',xy);print(tag,json.dumps(info));n.destroy_node();rclpy.try_shutdown()
