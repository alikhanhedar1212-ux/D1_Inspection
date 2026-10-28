"""Live local-reference estimates, deliberately without any motion publisher."""
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2

from door_reference_match import ReferenceMatcher, body_points

ROOT = Path(__file__).resolve().parent


def main():
    directory = Path(json.loads((ROOT/'door_references/latest.json').read_text())['directory'])
    metadata = json.loads((directory/'metadata.json').read_text())
    assert hashlib.sha256((directory/'reference.npz').read_bytes()).hexdigest() == metadata['reference_sha256']
    data = np.load(directory/'reference.npz')
    keys = sorted(k for k in data.files if k.startswith('cloud_') and k != 'cloud_stamps')
    matcher = ReferenceMatcher(body_points(np.concatenate([data[k] for k in keys[:len(keys)//2]])))
    rclpy.init()
    node = rclpy.create_node('read_only_door_reference_monitor')
    latest = {}

    def stamp(m):
        return m.header.stamp.sec + m.header.stamp.nanosec/1e9

    def cloud(m):
        latest['cloud'] = m

    def pose(m):
        latest['pose'] = m

    def report():
        now = time.time()
        result = dict(state='waiting', updated=now, automatic_adjustment_enabled=False,
                      reference_directory=str(directory), reference_sha256=metadata['reference_sha256'])
        try:
            cloud, pose = latest.get('cloud'), latest.get('pose')
            if cloud is None or pose is None:
                raise ValueError('等待实时点云和机身位置')
            if cloud.header.frame_id != 'nav_scan' or pose.header.frame_id != 'map':
                raise ValueError('传感器坐标系不匹配')
            if not -.05 <= now-stamp(cloud) < .7 or not -.05 <= now-stamp(pose) < .7:
                raise ValueError('实时数据过期')
            p, q = pose.pose.position, pose.pose.orientation
            anchor = metadata['target_map']
            yaw = 2*math.atan2(q.z, q.w)
            delta = math.atan2(math.sin(yaw-anchor['yaw']), math.cos(yaw-anchor['yaw']))
            distance = math.hypot(p.x-anchor['x'], p.y-anchor['y'])
            result.update(pose_map=[p.x, p.y, yaw], coarse_reference_distance_m=distance,
                          coarse_reference_yaw_error_deg=math.degrees(delta))
            if distance > 1.2 or abs(delta) > math.radians(45):
                raise ValueError('尚未进入门前局部匹配区域')
            raw = point_cloud2.read_points(cloud, field_names=('x', 'y', 'z'), skip_nans=True)
            points = np.column_stack([raw[k] for k in ('x', 'y', 'z')])
            result.update(matcher.match(body_points(points)), cloud_stamp=stamp(cloud),
                          source_age_s=now-stamp(cloud), pose_map=[p.x, p.y, yaw])
            if result['state'] == 'matched_read_only':
                dx, dy, a = result['reference_goal_in_current_body']
                result.update(position_error_m=math.hypot(dx, dy), yaw_error_deg=math.degrees(a))
        except (ValueError, KeyError, OSError) as exc:
            result.update(state='unavailable', reason=str(exc))
        path = ROOT/'door_reference_status.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        temp.replace(path)

    subscriptions = [node.create_subscription(PointCloud2, '/obstacle_points', cloud, qos_profile_sensor_data),
                     node.create_subscription(PoseStamped, '/body_pose', pose, 10)]
    node.create_timer(.5, report)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
