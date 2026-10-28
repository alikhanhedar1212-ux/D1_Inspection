from pathlib import Path
import yaml,subprocess,json,os
r=Path('/home/aidlux/navigation_preview');r.mkdir(exist_ok=True)
state=r/'processes.json'
if state.exists():
 for name,pid in json.loads(state.read_text()).items():
  if Path(f'/proc/{pid}/cmdline').exists():raise RuntimeError('定位输入已经运行，避免重复启动 '+name)
c=yaml.safe_load(Path('/home/aidlux/maps/floor_20261009_100455/mapping.yaml').read_text());p=c['/**']['ros__parameters'];p['common']['lid_topic']='/nav/lidar';p['common']['imu_topic']='/nav/imu';p['publish'].update({'map_en':False,'path_en':False,'effect_map_en':False,'scan_publish_en':False,'scan_bodyframe_pub_en':False});p['pcd_save']['pcd_save_en']=False;(r/'lio.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
base='source /opt/ros/humble/setup.bash; source /home/aidlux/agibot_d1_20260422/agibot_d1_ws/install/setup.bash; export ROS_DOMAIN_ID=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp OPENBLAS_NUM_THREADS=1; '
commands={'driver':'ros2 launch pacecat_m300_driver LDS-M300-E.launch','inputs':f'python3 -u {r}/live_inputs.py','lio':f'ros2 run fast_lio fastlio_mapping --ros-args --params-file {r}/lio.yaml -r /Odometry:=/nav/raw_odom -r /tf:=/nav/raw_tf'}
pids={}
for name,cmd in commands.items():
 log=(r/(name+'.log')).open('ab');proc=subprocess.Popen(['bash','-c',base+'exec '+cmd],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);pids[name]=proc.pid
state.write_text(json.dumps(pids));print(pids)
