from pathlib import Path
import json,math,time,sys,rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
root=Path(__file__).parent
if len(sys.argv)==4:x,y,yaw=map(float,sys.argv[1:])
else:
 p=json.loads((root/'initial_pose_candidates.json').read_text())['hypotheses'][0];x,y,yaw=p['x'],p['y'],p['yaw']
rclpy.init();n=rclpy.create_node('set_navigation_initial_hypothesis');pub=n.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
for _ in range(50):
 if pub.get_subscription_count():break
 time.sleep(.1)
m=PoseWithCovarianceStamped();m.header.frame_id='map';m.header.stamp=n.get_clock().now().to_msg();m.pose.pose.position.x=x;m.pose.pose.position.y=y;m.pose.pose.orientation.z=math.sin(yaw/2);m.pose.pose.orientation.w=math.cos(yaw/2);m.pose.covariance[0]=.25;m.pose.covariance[7]=.25;m.pose.covariance[35]=.0685;pub.publish(m);time.sleep(.5);print('已设置定位候选',x,y,yaw);n.destroy_node();rclpy.try_shutdown()
