"""Restart only the verified scan input process after a code update."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

root = Path('/home/aidlux/navigation_preview')
state = root / 'processes.json'
processes = json.loads(state.read_text())
pid = processes['inputs']
cmdline = Path(f'/proc/{pid}/cmdline')
expected = str(root / 'live_inputs.py').encode()
assert cmdline.exists() and expected in cmdline.read_bytes(), 'input PID does not match'
os.kill(pid, signal.SIGTERM)
deadline = time.monotonic() + 5
while cmdline.exists() and cmdline.read_bytes() and time.monotonic() < deadline:
    time.sleep(.1)
assert not cmdline.exists() or not cmdline.read_bytes(), 'old inputs still running'
command = ('source /opt/ros/humble/setup.bash; '
           'source /home/aidlux/agibot_d1_20260422/agibot_d1_ws/install/setup.bash; '
           'export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp OPENBLAS_NUM_THREADS=1; '
           'exec python3 -u /home/aidlux/navigation_preview/live_inputs.py')
with (root / 'inputs.log').open('ab') as log:
    process = subprocess.Popen(['bash','-c',command],stdin=subprocess.DEVNULL,
                               stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
processes['inputs'] = process.pid
state.write_text(json.dumps(processes))
print(json.dumps(processes))
