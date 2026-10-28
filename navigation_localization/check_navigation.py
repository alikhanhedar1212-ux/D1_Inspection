import time,json
from pathlib import Path
import rclpy
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import Twist
rclpy.init();n=rclpy.create_node('navigation_action_check');client=ActionClient(n,NavigateToPose,'/navigate_to_pose');cmds=[];n.create_subscription(Twist,'/nav_cmd_vel',lambda m:cmds.append([m.linear.x,m.linear.y,m.angular.z]),10)
def wait(f,timeout=15):
 end=time.monotonic()+timeout
 while not f.done() and time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
 if not f.done():raise TimeoutError()
 return f.result()
assert client.wait_for_server(timeout_sec=5)
g=NavigateToPose.Goal();g.pose.header.frame_id='map';g.pose.header.stamp=n.get_clock().now().to_msg();g.pose.pose.position.x=-1.;g.pose.pose.position.y=-2.;g.pose.pose.orientation.z=-.70710678;g.pose.pose.orientation.w=.70710678
h=wait(client.send_goal_async(g));assert h.accepted
end=time.monotonic()+8
while time.monotonic()<end:
 rclpy.spin_once(n,timeout_sec=.1)
 if any(abs(x)+abs(w)>1e-4 for x,y,w in cmds):break
cancel=wait(h.cancel_goal_async());result=wait(h.get_result_async());report={'hardware_forwarding':'disconnected during this test','goal_accepted':h.accepted,'velocity_samples':cmds,'result_after_cancel':result.status,'cancel_accepted':bool(cancel.goals_canceling)};Path(__file__).with_name('navigation_action_check.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));assert cmds and any(abs(x)+abs(w)>1e-4 for x,y,w in cmds);assert result.status==5
n.destroy_node();rclpy.try_shutdown()
