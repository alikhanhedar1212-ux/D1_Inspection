from project_config import local_path, setting, ros_prefix
import shlex
from pathlib import Path
import yaml,subprocess,json,os
r=Path(__file__).resolve().parent;r.mkdir(exist_ok=True)
state=r/'processes.json'
if state.exists():
 for name,pid in json.loads(state.read_text()).items():
  if Path(f'/proc/{pid}/cmdline').exists():raise RuntimeError('定位输入已经运行，避免重复启动 '+name)
c=yaml.safe_load(local_path(setting('mapping_config')).read_text());p=c['/**']['ros__parameters'];p['common']['lid_topic']='/nav/lidar';p['common']['imu_topic']='/nav/imu';p['publish'].update({'map_en':False,'path_en':False,'effect_map_en':False,'scan_publish_en':False,'scan_bodyframe_pub_en':False});p['pcd_save']['pcd_save_en']=False;(r/'lio.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
base=ros_prefix('aidlux')
commands={'driver':'ros2 launch pacecat_m300_driver LDS-M300-E.launch','inputs':'python3 -u '+shlex.quote(str(r/'live_inputs.py')),'lio':'ros2 run fast_lio fastlio_mapping --ros-args --params-file '+shlex.quote(str(r/'lio.yaml'))+' -r /Odometry:=/nav/raw_odom -r /tf:=/nav/raw_tf'}
pids={}
for name,cmd in commands.items():
 log=(r/(name+'.log')).open('ab');proc=subprocess.Popen(['bash','-c',base+'exec '+cmd],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);pids[name]=proc.pid
state.write_text(json.dumps(pids));print(pids)
