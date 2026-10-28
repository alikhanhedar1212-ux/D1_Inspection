import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deployment import motion_parameters
import os
from launch.actions import SetEnvironmentVariable
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    root = Path(__file__).parent
    vendor = root / "vendor/extracted/opt/ros/humble"
    return LaunchDescription([
        SetEnvironmentVariable("AMENT_PREFIX_PATH", str(vendor) + ":" + os.environ.get("AMENT_PREFIX_PATH", "")),
        SetEnvironmentVariable("LD_LIBRARY_PATH", str(root / "terminal_replan/build") + ":" + str(vendor / "lib") + ":" + str(vendor / "opt/openvdb_vendor/lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")),
        Node(package='nav2_map_server', executable='map_server', name='map_server', parameters=[{'yaml_filename': str(root / 'map.yaml'), 'use_sim_time': False, 'frame_id': 'map'}], output='screen'),
        Node(package='nav2_amcl', executable='amcl', name='amcl', parameters=[str(root / 'amcl.yaml')], output='screen'),
        Node(package='nav2_planner', executable='planner_server', name='planner_server', parameters=[str(root / 'planner.yaml')], output='screen'),
        Node(package='nav2_controller', executable='controller_server', name='controller_server', parameters=[motion_parameters('controller_server')], remappings=[('cmd_vel', '/nav_cmd_vel')], output='screen'),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server', parameters=[str(root / 'patrol_behaviors.yaml')], remappings=[('cmd_vel', '/nav_cmd_vel')], output='screen'),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator', parameters=[motion_parameters()], output='screen'),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_localization', parameters=[{'autostart': True, 'node_names': ['map_server', 'amcl']}], output='screen'),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_navigation', parameters=[{'autostart': True, 'node_names': ['planner_server', 'controller_server', 'behavior_server', 'bt_navigator']}], output='screen'),
    ])
