"""Run FollowPath with the hardware bridge stop latch engaged."""
import collections
import json
import time
import sys
from pathlib import Path
import rclpy
from rclpy.action import ActionClient
from lifecycle_msgs.srv import ChangeState
from nav2_msgs.action import ComputePathToPose, FollowPath
from std_srvs.srv import Trigger
from dwb_msgs.msg import LocalPlanEvaluation

rclpy.init()
n = rclpy.create_node('dwb_zero_motion_diagnostic')
def wait(f, seconds=12):
    rclpy.spin_until_future_complete(n, f, timeout_sec=seconds)
    if not f.done():
        raise TimeoutError('diagnostic request timed out')
    return f.result()

stop = n.create_client(Trigger, '/stop_navigation')
assert stop.wait_for_service(timeout_sec=5)
assert wait(stop.call_async(Trigger.Request())).success
# Reload the controller to read debug_trajectory_details, cached at configure.
change = n.create_client(ChangeState, '/controller_server/change_state')
assert change.wait_for_service(timeout_sec=5)
for transition in (() if '--configured' in sys.argv else (4, 2, 1, 3)):
    req = ChangeState.Request()
    req.transition.id = transition
    assert wait(change.call_async(req)).success

evaluations = []
subscriptions = []
end = time.monotonic() + 2
while time.monotonic() < end:
    rclpy.spin_once(n, timeout_sec=.1)
for topic, types in n.get_topic_names_and_types():
    if 'dwb_msgs/msg/LocalPlanEvaluation' in types:
        subscriptions.append(n.create_subscription(LocalPlanEvaluation, topic, evaluations.append, 10))
planner = ActionClient(n, ComputePathToPose, '/compute_path_to_pose')
assert planner.wait_for_server(timeout_sec=5)
g = ComputePathToPose.Goal()
g.goal.header.frame_id = 'map'
g.goal.header.stamp = n.get_clock().now().to_msg()
g.goal.pose.position.x = -9.42
g.goal.pose.position.y = -5.55
g.goal.pose.orientation.w = 1.
g.planner_id = 'GridBased'
handle = wait(planner.send_goal_async(g))
assert handle.accepted
result = wait(handle.get_result_async())
assert result.status == 4, f'ComputePathToPose failed: {result.status}'
controller = ActionClient(n, FollowPath, '/follow_path')
assert controller.wait_for_server(timeout_sec=5)
goal = FollowPath.Goal()
goal.path = result.result.path
goal.controller_id = 'FollowPath'
goal.goal_checker_id = 'general_goal_checker'
handle = wait(controller.send_goal_async(goal))
assert handle.accepted
future = handle.get_result_async()
end = time.monotonic() + 5
while not future.done() and time.monotonic() < end:
    rclpy.spin_once(n, timeout_sec=.1)
if not future.done():
    wait(handle.cancel_goal_async())
result = wait(future)
rejected = collections.Counter()
for evaluation in evaluations:
    for twist in evaluation.twists:
        if twist.total < 0:
            for score in twist.scores:
                if score.raw_score < 0:
                    rejected[score.name] += 1
report = {'hardware': 'stop_navigation latch engaged; no NavigateToPose goal',
          'goal': [-9.42, -5.55], 'result_status': result.status,
          'evaluations': len(evaluations), 'rejections': dict(rejected)}
Path(__file__).with_name('dwb_diagnostic.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
n.destroy_node()
rclpy.shutdown()
