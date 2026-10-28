"""Keep a compact record of trajectory rejection during real navigation."""
import collections
import json
import time
from pathlib import Path
import rclpy
from dwb_msgs.msg import LocalPlanEvaluation

rclpy.init()
n = rclpy.create_node('dwb_rejection_monitor')
root = Path(__file__).parent
last_write = 0.

def record(msg):
    global last_write
    rejected = collections.Counter()
    valid = 0
    for twist in msg.twists:
        if twist.total >= 0:
            valid += 1
        else:
            for score in twist.scores:
                if score.raw_score < 0:
                    rejected[score.name] += 1
    now = time.time()
    if valid and now - last_write < 1.:
        return
    last_write = now
    report = {'wall_time': now, 'ros_stamp': msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9,
              'total': len(msg.twists), 'valid': valid, 'rejected': dict(rejected)}
    with (root / 'runtime_logs/dwb_rejections.jsonl').open('a') as log:
        log.write(json.dumps(report) + '\n')
    (root / 'dwb_status.json').write_text(json.dumps(report))

subscriptions = {}
def discover():
    for topic, types in n.get_topic_names_and_types():
        if 'dwb_msgs/msg/LocalPlanEvaluation' in types and topic not in subscriptions:
            subscriptions[topic] = n.create_subscription(LocalPlanEvaluation, topic, record, 10)

n.create_timer(1., discover)
try:
    rclpy.spin(n)
finally:
    n.destroy_node()
    rclpy.try_shutdown()
