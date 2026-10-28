from pathlib import Path
import yaml,rclpy,math
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
from visualization_msgs.msg import Marker,MarkerArray
rclpy.init();n=rclpy.create_node('waypoint_review_markers');p=n.create_publisher(MarkerArray,'/waypoint_candidates',QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL));items=yaml.safe_load(Path(__file__).with_name('waypoints.yaml').read_text())['waypoints'];a=MarkerArray()
for w in items:
 m=Marker();m.header.frame_id='map';m.ns='stop_points';m.id=w['id'];m.type=Marker.SPHERE;m.action=Marker.ADD;m.pose.position.x=w['x'];m.pose.position.y=w['y'];m.pose.position.z=.1;m.pose.orientation.w=1.;m.scale.x=m.scale.y=m.scale.z=.25;m.color.r=.05;m.color.g=.5;m.color.b=1.;m.color.a=1.;a.markers.append(m)
 t=Marker();t.header.frame_id='map';t.ns='stop_labels';t.id=w['id'];t.type=Marker.TEXT_VIEW_FACING;t.action=Marker.ADD;t.pose.position.x=w['x'];t.pose.position.y=w['y'];t.pose.position.z=.7;t.pose.orientation.w=1.;t.scale.z=.55;t.color.r=.05;t.color.g=.3;t.color.b=.9;t.color.a=1.;t.text=str(w['id']);a.markers.append(t)

import json
config=json.loads((Path(__file__).parent.parent/'voice_navigation/patrol_config.json').read_text())
for ident,w in config['points'].items():
 m=Marker();m.header.frame_id='map';m.ns='patrol_direction';m.id=int(ident);m.type=Marker.ARROW;m.action=Marker.ADD;m.pose.position.x=w['x'];m.pose.position.y=w['y'];m.pose.position.z=.2;m.pose.orientation.z=math.sin(w['yaw']/2);m.pose.orientation.w=math.cos(w['yaw']/2);m.scale.x=.8;m.scale.y=.12;m.scale.z=.15;m.color.r=1.;m.color.g=.2;m.color.a=1.;a.markers.append(m)
 t=Marker();t.header.frame_id='map';t.ns='patrol_labels';t.id=int(ident);t.type=Marker.TEXT_VIEW_FACING;t.pose.position.x=w['x'];t.pose.position.y=w['y'];t.pose.position.z=1.;t.pose.orientation.w=1.;t.scale.z=.4;t.color.r=1.;t.color.a=1.;t.text='P'+ident;a.markers.append(t)
for index,(name,route) in enumerate(config['return_routes'].items()):
 from geometry_msgs.msg import Point
 m=Marker();m.header.frame_id='map';m.ns='patrol_return_routes';m.id=index;m.type=Marker.LINE_STRIP;m.pose.orientation.w=1.;m.scale.x=.06;m.color.r=float(name=='left');m.color.g=float(name=='right');m.color.a=1.
 for w in [config['points']['4']]+route:
  q=Point();q.x=w['x'];q.y=w['y'];q.z=.15;m.points.append(q)
 a.markers.append(m)

p.publish(a)
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
