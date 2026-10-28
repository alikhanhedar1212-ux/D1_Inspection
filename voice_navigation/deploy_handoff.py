"""Load the idle voice handoff without issuing a motion goal."""
import os,signal,subprocess,time,json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
voice=root/'voice_navigation'
state=root/'navigation_localization/restored_processes.json'
pids=json.loads(state.read_text())
def spawn(name,command):
    log=(root/'navigation_localization/runtime_logs'/f'{name}_handoff.log').open('ab')
    p=subprocess.Popen(['bash','-c','source /home/hcb/aidlux_mapping_view/navigation_localization/runtime_env.sh; exec '+command],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    log.close();pids[name]=p.pid
    return p
old=int((voice/'listener.pid').read_text())
path=Path(f'/proc/{old}/cmdline')
if path.exists() and str(voice/'voice_navigation.py').encode() in path.read_bytes():
    os.kill(old,signal.SIGINT)
    for _ in range(100):
        if not path.exists():break
        time.sleep(.05)
    else:raise RuntimeError('语音程序尚未退出，不重复启动')
bridge=pids.get('velocity_bridge',0)
path=Path(f'/proc/{bridge}/cmdline')
if not path.exists() or b'/velocity_bridge.py' not in path.read_bytes():
    spawn('velocity_bridge',f'python3 -u {root}/navigation_localization/velocity_bridge.py')
spawn('handoff_backend',f'python3 -u {root}/stairs_mapping/realtime/handoff_backend.py')
spawn('voice',f'{voice}/.venv/bin/python -u {voice}/voice_navigation.py --computer-mic --execute --source alsa_input.usb-Newmine_Newmine_20180508-00.analog-stereo')
state.write_text(json.dumps(pids,indent=2))
print(json.dumps({k:pids[k] for k in ('voice','velocity_bridge','handoff_backend')}))
