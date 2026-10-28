"""Reload perception transport and costmaps while motion is stopped."""
import json
import math
import os
import signal
import subprocess
import time
from pathlib import Path
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_srvs.srv import Trigger

root = Path(__file__).parent
state = root/'restored_processes.json'; processes = json.loads(state.read_text())
env = dict(os.environ,ROS_DOMAIN_ID='93',ROS_LOCALHOST_ONLY='1',RMW_IMPLEMENTATION='rmw_cyclonedds_cpp')
# Recover a disconnected perception transport before trying to capture a live pose.
old = Path(f'/proc/{processes["stream_receiver"]}/cmdline')
if not old.exists() or not old.read_bytes():
    with (root/'runtime_logs/stream_receiver.log').open('ab') as log:
        process = subprocess.Popen(['bash','-c',f'source /home/hcb/aidlux_mapping_view/navigation_localization/runtime_env.sh; exec python3 -u {root}/stream_receiver.py'],
                                   env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    processes['stream_receiver']=process.pid;state.write_text(json.dumps(processes,indent=2))
rclpy.init(); n = rclpy.create_node('voxel_reload_guard')
c = n.create_client(Trigger, '/stop_navigation')
assert c.wait_for_service(timeout_sec=5)
f = c.call_async(Trigger.Request()); rclpy.spin_until_future_complete(n,f,timeout_sec=5)
assert f.done() and f.result().success
poses = []
s = n.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',poses.append,10)
end = time.monotonic()+5
while not poses and time.monotonic()<end: rclpy.spin_once(n,timeout_sec=.1)
# Ask AMCL for a no-motion update to publish its current pose.
if not poses:
    from std_srvs.srv import Empty
    refresh = n.create_client(Empty,'/request_nomotion_update')
    assert refresh.wait_for_service(timeout_sec=3)
    refresh.call_async(Empty.Request())
    end = time.monotonic()+5
    while not poses and time.monotonic()<end: rclpy.spin_once(n,timeout_sec=.1)
assert poses, 'No live pose; do not reload localization without it'
m = poses[-1]; p=m.pose.pose.position; q=m.pose.pose.orientation
pose = [p.x,p.y,2*math.atan2(q.z,q.w)]
(root/'pose_before_voxel_reload.json').write_text(json.dumps(pose))
n.destroy_node(); rclpy.shutdown()
processes = json.loads(state.read_text())
for name, token in [('navigation','restore.launch.py'),('stream_receiver','stream_receiver.py')]:
    pid = processes[name]; cmd = Path(f'/proc/{pid}/cmdline')
    assert cmd.exists() and token.encode() in cmd.read_bytes(), f'Wrong PID for {name}'
    assert os.getpgid(pid)==pid, 'Expected isolated process group'
    os.killpg(pid,signal.SIGINT)
    end = time.monotonic()+10
    while cmd.exists() and cmd.read_bytes() and time.monotonic()<end: time.sleep(.1)
    assert not cmd.exists() or not cmd.read_bytes(), f'{name} failed to exit'
env = dict(os.environ,ROS_DOMAIN_ID='93',ROS_LOCALHOST_ONLY='1',RMW_IMPLEMENTATION='rmw_cyclonedds_cpp')
commands = {'stream_receiver':f'python3 -u {root}/stream_receiver.py',
            'navigation':f'ros2 launch {root}/restore.launch.py'}
for name, command in commands.items():
    with (root/'runtime_logs'/f'{name}.log').open('ab') as log:
        process = subprocess.Popen(['bash','-c','source /home/hcb/aidlux_mapping_view/navigation_localization/runtime_env.sh; exec '+command],
                                   env=env,stdin=subprocess.DEVNULL,stdout=log,
                                   stderr=subprocess.STDOUT,start_new_session=True)
        processes[name]=process.pid
state.write_text(json.dumps(processes,indent=2))
print('Restarted perception and navigation; saved live pose:',pose)
