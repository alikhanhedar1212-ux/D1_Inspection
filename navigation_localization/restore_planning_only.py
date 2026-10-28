"""Restore perception and planning without a hardware velocity bridge."""
from project_config import ui_path
import json
import os
import subprocess
import shlex
from pathlib import Path

root = Path(__file__).resolve().parent
(root / "runtime_logs").mkdir(exist_ok=True)
state = root / 'restored_processes.json'
if state.exists():
    for name, pid in json.loads(state.read_text()).items():
        proc_path = Path(f'/proc/{pid}/cmdline')
        if proc_path.exists() and str(root).encode() in proc_path.read_bytes():
            raise RuntimeError(f'导航进程仍在运行，避免重复启动: {name} ({pid})')
env = dict(os.environ, ROS_DOMAIN_ID='93', ROS_LOCALHOST_ONLY='1',
           RMW_IMPLEMENTATION='rmw_cyclonedds_cpp', LIBGL_ALWAYS_SOFTWARE='true',
           __GLX_VENDOR_LIBRARY_NAME='mesa', MESA_GL_VERSION_OVERRIDE='3.3',
           QT_XCB_GL_INTEGRATION='xcb_glx')
commands = {name: shlex.join(['python3', '-u', str(root / (name + '.py'))]) for name in
            ('stream_receiver', 'body_frame', 'navigation_scan_filter', 'map_display',
            'waypoint_markers', 'clearance_map', 'dwb_monitor', 'goal_alignment_monitor',
            'auto_localization')}
commands['navigation'] = shlex.join(['ros2', 'launch', str(root / 'restore.launch.py')])
commands['camera_receiver'] = shlex.join(['python3', '-u', str(root.parent / 'drivers/camera_receiver.py')])
commands['rviz'] = shlex.join(['rviz2', '-d', str(ui_path('rviz/navigation_drive.rviz'))])
pids = {}
for name, command in commands.items():
    with (root / 'runtime_logs' / (name + '.log')).open('ab') as log:
        process = subprocess.Popen(
            ['bash', '-c', f'source {shlex.quote(str(root / "runtime_env.sh"))} && exec ' + command],
            env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True)
        pids[name] = process.pid
state.write_text(json.dumps(pids, indent=2))
print(json.dumps(pids))
