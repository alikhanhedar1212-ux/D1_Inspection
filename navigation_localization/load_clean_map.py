from project_config import map_path
from pathlib import Path
import time,json
import rclpy
from rclpy.qos import QoSProfile,DurabilityPolicy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.srv import LoadMap
rclpy.init();n=rclpy.create_node('load_cleaned_navigation_map');poses=[];n.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',poses.append,QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
end=time.monotonic()+5
while not poses and time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
assert poses,'当前定位未收到，停止地图替换';pose=poses[-1]
c=n.create_client(LoadMap,'/map_server/load_map');assert c.wait_for_service(timeout_sec=5);req=LoadMap.Request();req.map_url=str(map_path('map.yaml'));f=c.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=10);assert f.done() and f.result().result==0
pub=n.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
end=time.monotonic()+2
while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
pose.header.stamp=n.get_clock().now().to_msg();pub.publish(pose)
for _ in range(10):rclpy.spin_once(n,timeout_sec=.1)
print('已加载清理地图并保留定位',pose.pose.pose.position.x,pose.pose.pose.position.y);n.destroy_node();rclpy.try_shutdown()
