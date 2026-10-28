from pathlib import Path
import os
from launch.actions import SetEnvironmentVariable
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
 root=Path(__file__).parent
 vendor=root/"vendor/extracted/opt/ros/humble"
 return LaunchDescription([
  SetEnvironmentVariable("AMENT_PREFIX_PATH",str(vendor)+":"+os.environ.get("AMENT_PREFIX_PATH","")),
  SetEnvironmentVariable("LD_LIBRARY_PATH",str(vendor/"lib")+":"+str(vendor/"opt/openvdb_vendor/lib")+":"+os.environ.get("LD_LIBRARY_PATH","")),
  Node(package='nav2_map_server',executable='map_server',name='map_server',output='screen',parameters=[{'yaml_filename':str(root/'map.yaml'),'use_sim_time':False,'frame_id':'map'}]),
  Node(package='nav2_amcl',executable='amcl',name='amcl',output='screen',parameters=[str(root/'amcl.yaml')]),
  Node(package='nav2_planner',executable='planner_server',name='planner_server',output='screen',parameters=[str(root/'planner.yaml')]),
  Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='lifecycle_manager_localization',output='screen',parameters=[{'autostart':True,'use_sim_time':False,'node_names':['map_server','amcl']}]),
 ])
