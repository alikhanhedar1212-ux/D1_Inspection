"""Read-only compare local lethal cells with the static map and scans."""
import json
import time
from pathlib import Path
import numpy as np
import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

rclpy.init(); n = rclpy.create_node('near_obstacle_check')
buf = Buffer(); listener = TransformListener(buf, n)
messages = {}
qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
subs = [n.create_subscription(OccupancyGrid, topic, lambda m, k=k: messages.__setitem__(k,m), qos)
        for k,topic in [('map','/map'),('local','/local_costmap/costmap')]]
subs += [n.create_subscription(LaserScan, topic, lambda m,k=k: messages.__setitem__(k,m), 5)
         for k,topic in [('scan','/scan'),('obstacle','/obstacle_scan')]]
end = time.monotonic()+4
while time.monotonic()<end: rclpy.spin_once(n,timeout_sec=.1)
assert all(k in messages for k in ('map','local','scan','obstacle'))
grid = messages['local']; static = messages['map']; info = grid.info
data = np.array(grid.data).reshape(info.height,info.width)
body = buf.lookup_transform(grid.header.frame_id,'nav_body',rclpy.time.Time())
yy,xx = np.where(data==100)
x = info.origin.position.x+(xx+.5)*info.resolution
y = info.origin.position.y+(yy+.5)*info.resolution
distance = np.hypot(x-body.transform.translation.x,y-body.transform.translation.y)
near = distance<1.
t = buf.lookup_transform('map',grid.header.frame_id,rclpy.time.Time())
yaw = 2*np.arctan2(t.transform.rotation.z,t.transform.rotation.w)
mx = np.cos(yaw)*x-np.sin(yaw)*y+t.transform.translation.x
my = np.sin(yaw)*x+np.cos(yaw)*y+t.transform.translation.y
si = static.info; ix = np.floor((mx-si.origin.position.x)/si.resolution).astype(int)
iy = np.floor((my-si.origin.position.y)/si.resolution).astype(int)
inside = (ix>=0)&(iy>=0)&(ix<si.width)&(iy<si.height)
static_data = np.array(static.data).reshape(si.height,si.width)
static_values = np.full(len(ix),-1); static_values[inside] = static_data[iy[inside],ix[inside]]
report = {'updated':time.time(),'near_1m_lethal_cells':int(near.sum()),
          'near_1m_lethal_on_static_free':int((near&(static_values==0)).sum()),
          'nearest_lethal_m':float(distance.min()) if len(distance) else None,
          'scans':{}}
for k in ('scan','obstacle'):
    scan = messages[k]; a = np.array(scan.ranges); indices = np.flatnonzero(np.isfinite(a)&(a<1.))
    report['scans'][k] = {'finite':int(np.isfinite(a).sum()),'nan':int(np.isnan(a).sum()),
                         'inf':int(np.isinf(a).sum()), 'near_beams':[[int(i),round(float(a[i]),3)] for i in indices]}
root = Path(__file__).parent
(root/'near_obstacles.json').write_text(json.dumps(report,indent=2))
np.savez_compressed(root/'near_obstacles.npz', local=data, lethal_xy=np.column_stack((x,y)), static_values=static_values)
print(json.dumps(report))
n.destroy_node(); rclpy.shutdown()
