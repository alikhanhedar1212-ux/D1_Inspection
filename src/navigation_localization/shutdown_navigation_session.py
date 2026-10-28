"""Stop this project's navigation experiment, preserving robot core services and maps."""
from project_config import remote_file, setting, ssh_command
import json,os,signal,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
NAV=ROOT/'src/navigation_localization'
SELF=Path(__file__).resolve()

def processes():
    result={}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            args=[os.fsdecode(a) for a in (p/'cmdline').read_bytes().split(b'\0') if a]
            parent=int((p/'stat').read_text().rsplit(')',1)[1].split()[1])
            result[int(p.name)]=(parent,args)
        except (OSError,ValueError,IndexError):pass
    return result

def stop_set(snapshot,targets):
    for pid in sorted(targets,reverse=True):
        try:
            if processes().get(pid)==snapshot.get(pid):os.kill(pid,signal.SIGINT)
        except ProcessLookupError:pass
    end=time.monotonic()+3
    while time.monotonic()<end:
        current=processes()
        if not any(current.get(p)==snapshot.get(p) and current[p][1] for p in targets):break
        time.sleep(.1)
    for pid in targets:
        try:
            current=processes().get(pid)
            if current==snapshot.get(pid) and current[1]:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass

record={'started':time.time(),'robot_core_services_preserved':True}
# An unavailable stop service does not delay process cleanup indefinitely.
stop_code="""import rclpy,json
from std_srvs.srv import Trigger
rclpy.init();n=rclpy.create_node('shutdown_navigation_safely');c=n.create_client(Trigger,'/stop_navigation')
if c.wait_for_service(timeout_sec=2):
 f=c.call_async(Trigger.Request());rclpy.spin_until_future_complete(n,f,timeout_sec=2)
 print(json.dumps({'success':bool(f.done() and f.result().success)}))
else:print(json.dumps({'service_available':False}))
n.destroy_node();rclpy.try_shutdown()
"""
try:
    result=subprocess.run(['python3','-c',stop_code],capture_output=True,text=True,timeout=6)
    record['stop_service']={'returncode':result.returncode,'output':result.stdout,'error':result.stderr}
except subprocess.TimeoutExpired:record['stop_service']={'timeout':True}

ps=processes();roots=set()
for pid,(_,args) in ps.items():
    if pid==os.getpid() or not args:continue
    # Only executable arguments, never a shell's embedded command text.
    project_scripts=[a for a in args[1:] if a.endswith('.py') and a.startswith(str(ROOT)+'/') and a!=str(SELF)]
    if Path(args[0]).name.startswith('python') and project_scripts:
        if any('/navigation_localization/' in a or '/voice_navigation/' in a or '/stairs_mapping/' in a or '/drivers/' in a for a in project_scripts):roots.add(pid)
    if Path(args[0]).name=='rviz2' and any(a.startswith(str(ROOT)+'/') and a.endswith('.rviz') for a in args):roots.add(pid)
    if args[0].startswith(str(ROOT/'stairs_mapping/jie_3d_ws/install')+'/'):roots.add(pid)
    if (Path(args[0]).name=='ssh' and any(setting(role+'_host') in args for role in ('aidlux','firefly'))
            and any(token in a for token in ('velocity_receiver.py','stream_sender.py','clock_probe.py','camera_sender_latest.py') for a in args)):
        roots.add(pid)
targets=set(roots)
while True:
    children={p for p,(parent,args) in ps.items() if parent in targets}
    if children<=targets:break
    targets|=children
# First stop command producers, then the velocity bridge, then other children.
voice={p for p in targets if any('/voice_navigation/' in a or 'handoff_backend.py' in a for a in ps[p][1])}
stop_set(ps,voice)
bridges={p for p in targets if str(NAV/'velocity_bridge.py') in ps[p][1]}
stop_set(ps,bridges)
stop_set(ps,targets-voice-bridges)
record['local_stopped']=[{'pid':p,'args':ps[p][1]} for p in sorted(targets)]

remote=r'''import os,signal,time,json
from pathlib import Path
HOST=__HOST__
NAVDIR=str(Path(__NAVDIR__).expanduser().resolve())
VOICEDIR=str(Path(__VOICEDIR__).expanduser().resolve())
CAMERA=str(Path(__CAMERA__).expanduser().resolve())
def scan():
 out={}
 for p in Path('/proc').glob('[0-9]*'):
  try:
   args=[os.fsdecode(a) for a in (p/'cmdline').read_bytes().split(b'\0') if a]
   parent=int((p/'stat').read_text().rsplit(')',1)[1].split()[1]);out[int(p.name)]=(parent,args)
  except (OSError,ValueError,IndexError):pass
 return out
ps=scan();targets=set()
for pid,(parent,args) in ps.items():
 if pid==os.getpid() or not args:continue
 if HOST=='aidlux':
  match=any(a.startswith(NAVDIR+'/') for a in args[1:] if a.endswith('.py'))
  match=match or any(a in (CAMERA,VOICEDIR+'/audio_sender.py',VOICEDIR+'/play_reply.py') for a in args[1:])
 else:match=NAVDIR+'/velocity_receiver.py' in args
 if match:targets.add(pid)
if HOST=='aidlux':
 for state in (Path(NAVDIR)/'processes.json',):
  if state.exists():
   for pid in json.loads(state.read_text()).values():
    if pid in ps and any('pacecat_m300_driver' in a or 'fast_lio' in a or NAVDIR+'/' in a for a in ps[pid][1]):targets.add(pid)
while True:
 children={p for p,(parent,args) in ps.items() if parent in targets}
 if children<=targets:break
 targets|=children
for pid in sorted(targets,reverse=True):
 try:os.kill(pid,signal.SIGINT)
 except ProcessLookupError:pass
end=time.monotonic()+3
while time.monotonic()<end:
 current=scan()
 if not any(current.get(p)==ps.get(p) and current[p][1] for p in targets):break
 time.sleep(.1)
for pid in targets:
 try:
  current=scan().get(pid)
  if current==ps.get(pid) and current[1]:os.kill(pid,signal.SIGKILL)
 except ProcessLookupError:pass
if HOST=='aidlux':
 for state in (Path(NAVDIR)/'processes.json',):
  if state.exists():state.write_text('{}\n')
print(json.dumps({'host':HOST,'stopped':[{'pid':p,'args':ps[p][1]} for p in sorted(targets)]}))
'''
record['remote']=[]
for host in ('aidlux','firefly'):
    try:
        code=(remote.replace('__HOST__',repr(host))
              .replace('__NAVDIR__',repr(remote_file(host,'drivers')))
              .replace('__VOICEDIR__',repr(remote_file(host,'voice_navigation')))
              .replace('__CAMERA__',repr(remote_file(host,'drivers','camera_sender_latest.py'))))
        result=subprocess.run(ssh_command(host,['python3','-'],timeout=5),input=code,capture_output=True,text=True,timeout=15)
        record['remote'].append({'host':host,'returncode':result.returncode,'output':result.stdout,'error':result.stderr})
    except subprocess.TimeoutExpired:record['remote'].append({'host':host,'timeout':True})
state=NAV/'restored_processes.json'
if state.exists():record['previous_process_state']=json.loads(state.read_text())
state.write_text('{}\n')
record['finished']=time.time();path=NAV/('shutdown_'+time.strftime('%Y%m%d_%H%M%S')+'.json');path.write_text(json.dumps(record,ensure_ascii=False,indent=2))
print(json.dumps({'record':str(path),'local_stopped':len(targets),'remote':[{'host':x['host'],'returncode':x.get('returncode'),'timeout':x.get('timeout',False)} for x in record['remote']]},ensure_ascii=False))
