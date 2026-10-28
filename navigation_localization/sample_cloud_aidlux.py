"""Read-only capture of points using the live scan projection geometry."""
import ast
import json
import time
from pathlib import Path
import numpy as np
import rclpy
from rclpy.qos import qos_profile_sensor_data
from scipy.spatial.transform import Rotation
from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from pacecat_m300_inter.msg import CustomMsg

root = Path('/home/aidlux/navigation_preview')
tree = ast.parse((root / 'live_inputs.py').read_text())
imports = [item for item in tree.body if isinstance(item, (ast.Import, ast.ImportFrom))]
defs = [item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'decode']
assigns = [item for item in tree.body if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'POINT' for t in item.targets)]
namespace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=imports + assigns + defs, type_ignores=[])), '<decode>', 'exec'), namespace)
decode = namespace['decode']
rclpy.init()
n = rclpy.create_node('read_only_scan_cloud_capture')
clouds, poses, accelerations = [], [], []
def cloud(data):
    clouds.append(decode(data))
    del clouds[:-10]
def pose(m):
    p, q = m.pose.pose.position, m.pose.pose.orientation
    poses.append([m.header.stamp.sec+m.header.stamp.nanosec*1e-9, p.x, p.y, p.z, q.x, q.y, q.z, q.w])
    del poses[:-200]
def imu(m):
    a = m.linear_acceleration
    accelerations.append([a.x, a.y, a.z])
    del accelerations[:-500]
n.create_subscription(CustomMsg, '/custommsg', cloud, 1, raw=True)
n.create_subscription(Odometry, '/nav/raw_odom', pose, 10)
n.create_subscription(Imu, '/m300_imu', imu, qos_profile_sensor_data)
end = time.monotonic()+5
while time.monotonic() < end:
    rclpy.spin_once(n, timeout_sec=.1)
assert clouds and len(poses)>2 and len(accelerations)>100
g = np.mean(accelerations, axis=0); g /= np.linalg.norm(g)
v = np.cross(g, [0,0,1]); k = np.array([[0,-v[2],v[1]],[v[2],0,-v[0]],[-v[1],v[0],0]])
level = np.eye(3)+k+k@k/(1+g[2])
poses = np.asarray(poses)
samples = []
for t, raw in clouds:
    end = t+raw[:,3].max()*1e-9
    if t<poses[0,0] or end>poses[-1,0]:
        continue
    valid = np.isfinite(raw[:,:3]).all(axis=1)&(np.linalg.norm(raw[:,:3],axis=1)>.4)&(raw[:,4]==0)
    raw = raw[valid]
    pt = t+raw[:,3]*1e-9; center = (t+end)/2
    values = np.column_stack([np.interp(pt,poses[:,0],poses[:,j]) for j in range(1,8)])
    q = values[:,3:]; q /= np.linalg.norm(q,axis=1)[:,None]
    pc = np.array([np.interp(center,poses[:,0],poses[:,j]) for j in range(1,8)])
    qc = pc[3:]/np.linalg.norm(pc[3:])
    rot = level@Rotation.from_quat(qc).as_matrix(); yaw = np.arctan2(rot[1,0],rot[0,0])
    ext = np.array([[0,1,0],[-1,0,0],[0,0,1]])
    world = Rotation.from_quat(q).apply(raw[:,:3]@ext.T+np.array([.0178,-.0049,-.0383]))+values[:,:3]
    relative = world@level.T-pc[:3]@level.T
    local = relative@np.array([[np.cos(yaw),-np.sin(yaw),0],[np.sin(yaw),np.cos(yaw),0],[0,0,1]])
    samples.append(local)
assert samples
np.savez_compressed(root/'cloud_diagnostic.npz', **{f'cloud{i}':a for i,a in enumerate(samples)})
floor = json.loads((root/'input_status.json').read_text())['floor_m']
report = {'frames':len(samples), 'floor':floor, 'points':[]}
for local in samples:
    d = np.linalg.norm(local[:,:2],axis=1)
    good = (local[:,2]-floor>=.2)&(local[:,2]-floor<=1.4)&(d>=.5)&(d<=20)
    near = good&(d<1.)
    report['points'].append({'obstacle':int(good.sum()), 'near_1m':int(near.sum()),
                            'near_xyz':local[near][:20].round(3).tolist()})
print(json.dumps(report))
n.destroy_node(); rclpy.shutdown()
