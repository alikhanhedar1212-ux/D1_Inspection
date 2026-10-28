"""Passive ROS observation; creates no command publishers."""
import json
import time
import rclpy
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.convert import message_to_ordereddict
from robots_dog_msgs.msg import HighLevelCmd, HighLevelRobotState, McState

rclpy.init()
node = rclpy.create_node('observe_greet_read_only')
start = time.monotonic()
last_body = 0.0
counts = {}

def record(topic, msg):
    global last_body
    counts[topic] = counts.get(topic, 0) + 1
    now = time.monotonic()
    if topic == '/highlevel_robotstate':
        if now - last_body < .1:
            return
        last_body = now
    print(json.dumps({'elapsed': round(now-start, 3), 'topic': topic,
                      'data': message_to_ordereddict(msg)}, ensure_ascii=False), flush=True)

subscriptions = [node.create_subscription(kind, topic, lambda msg, t=topic: record(t, msg),
                    qos_profile_sensor_data) for topic, kind in (
    ('/highlevel_cmd', HighLevelCmd),
    ('/highlevel_robotstate', HighLevelRobotState),
    ('/arc/mc_state', McState))]
print(json.dumps({'observer': 'ready', 'duration_seconds': 900}), flush=True)
try:
    while time.monotonic() - start < 900:
        rclpy.spin_once(node, timeout_sec=.1)
finally:
    print(json.dumps({'observer': 'finished', 'counts': counts}), flush=True)
    node.destroy_node()
    rclpy.try_shutdown()
