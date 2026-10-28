"""Capture a user-approved stationary door-wait reference; publishes no ROS messages."""
import datetime
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan, PointCloud2
from sensor_msgs_py import point_cloud2
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parent


def main():
    rclpy.init()
    node = rclpy.create_node('read_only_door_reference_capture')
    clouds, scans, poses, motion, errors = [], [], [], [], []
    camera = []

    def stamp(m):
        return m.header.stamp.sec + m.header.stamp.nanosec / 1e9

    def cloud(m):
        if m.header.frame_id != 'nav_scan' or not -.05 <= time.time()-stamp(m) < .7:
            errors.append('stale cloud or unexpected cloud frame')
            return
        a = point_cloud2.read_points(m, field_names=('x', 'y', 'z'), skip_nans=True)
        a = np.column_stack([a[k] for k in ('x', 'y', 'z')])
        clouds.append((stamp(m), a))

    def scan(m):
        scans.append((stamp(m), m.angle_min, m.angle_increment, np.asarray(m.ranges)))

    def pose(m):
        if m.header.frame_id != 'map':
            errors.append('unexpected pose frame')
            return
        p, q = m.pose.position, m.pose.orientation
        poses.append([stamp(m), p.x, p.y, 2*math.atan2(q.z, q.w)])

    def odom(m):
        v = m.twist.twist
        motion.append([stamp(m), v.linear.x, v.linear.y, v.angular.z, time.time()])

    def image(m):
        if camera or m.encoding not in ('bgr8', 'rgb8'):
            return
        a = np.frombuffer(m.data, dtype=np.uint8).reshape(m.height, m.step)
        a = a[:, :m.width*3].reshape(m.height, m.width, 3)
        camera.append((stamp(m), a[:, :, ::-1].copy() if m.encoding == 'bgr8' else a.copy()))

    subscriptions = [
        node.create_subscription(PointCloud2, '/obstacle_points', cloud, qos_profile_sensor_data),
        node.create_subscription(LaserScan, '/scan', scan, qos_profile_sensor_data),
        node.create_subscription(PoseStamped, '/body_pose', pose, 10),
        node.create_subscription(Odometry, '/body_odom', odom, 10),
        node.create_subscription(Image, '/dog_camera/image_raw', image, qos_profile_sensor_data),
    ]
    try:
        end = time.monotonic()+8
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.1)
        assert not errors, errors[:5]
        assert len(clouds) >= 25 and len(scans) >= 25 and len(poses) >= 30 and len(motion) >= 50
        poses, motion = np.asarray(poses), np.asarray(motion)
        assert np.isfinite(poses).all() and np.isfinite(motion).all()
        assert np.max(np.abs(motion[:, 4]-motion[:, 0])) < .7, 'stale odometry'
        assert np.max(np.diff(motion[:, 0])) < .7 and np.min(np.diff(motion[:, 0])) > 0
        # Match the runtime standstill gate: a continuous recent interval, plus
        # bounded pose variation over the entire reference. A derivative spike
        # early in the capture must not masquerade as continuing movement.
        recent = motion[motion[:, 0] >= motion[-1, 0]-1.0]
        assert len(recent) >= 7 and recent[-1, 0]-recent[0, 0] >= .6
        assert np.max(np.linalg.norm(recent[:, 1:3], axis=1)) < .03, 'base is moving'
        assert np.max(np.abs(recent[:, 3])) < .05, 'base is rotating'
        yaw = np.unwrap(poses[:, 3])
        assert np.linalg.norm(np.ptp(poses[:, 1:3], axis=0)) < .05, 'pose not stationary'
        assert np.ptp(yaw) < math.radians(2), 'yaw not stationary'
        bridge = json.loads((ROOT/'velocity_bridge_status.json').read_text())
        assert -.05 <= time.time()-bridge['updated'] < 3
        assert all(abs(bridge[k]) < .001 for k in ('x', 'y', 'w')), 'nonzero command'
        assert bridge.get('goal_id') is None, 'navigation goal still active'
        target = [float(np.median(poses[:, 1])), float(np.median(poses[:, 2])),
                  math.atan2(np.sin(yaw).mean(), np.cos(yaw).mean())]
        directory = ROOT/'door_references'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        directory.mkdir(parents=True, exist_ok=False)
        arrays = {f'cloud_{i:03d}': a for i, (_, a) in enumerate(clouds)}
        arrays.update(cloud_stamps=np.array([t for t, _ in clouds]),
                      scans=np.stack([s[3] for s in scans]),
                      scan_parameters=np.array([s[:3] for s in scans]), poses=poses, motion=motion)
        np.savez_compressed(directory/'reference.npz', **arrays)
        if camera:
            PILImage.fromarray(camera[0][1]).save(directory/'camera.png')
        metadata = {
            'captured_at': time.time(), 'user_approved_wait_pose': True,
            'cloud_frame': 'nav_scan', 'pose_frame': 'map',
            'target_map': dict(zip(('x', 'y', 'yaw'), target)),
            'frames': len(clouds), 'scan_frames': len(scans), 'motion_frames': len(motion),
            'pose_span_xy_m': np.ptp(poses[:, 1:3], axis=0).tolist(),
            'yaw_span_deg': float(np.degrees(np.ptp(yaw))),
            'maximum_measured_speed_m_s': float(np.linalg.norm(motion[:, 1:3], axis=1).max()),
            'maximum_measured_yaw_speed_rad_s': float(abs(motion[:, 3]).max()),
            'standstill_gate': {'duration_s': float(recent[-1, 0]-recent[0, 0]),
                                'maximum_speed_m_s': float(np.linalg.norm(recent[:, 1:3], axis=1).max()),
                                'maximum_yaw_speed_rad_s': float(abs(recent[:, 3]).max()),
                                'whole_capture_pose_checked': True},
            'velocity_bridge': bridge, 'camera_stamp': camera[0][0] if camera else None,
            'reference_sha256': hashlib.sha256((directory/'reference.npz').read_bytes()).hexdigest(),
            'automatic_adjustment_enabled': False,
            'note': 'User-approved local scene reference, not a verified doorway or free-space detection. No motion authorized by capture.',
        }
        (directory/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        # The pointer is changed only after the complete, validated capture exists.
        pointer = ROOT/'door_references/latest.json'
        temp = pointer.with_suffix('.tmp')
        temp.write_text(json.dumps({'directory': str(directory)}, indent=2))
        temp.replace(pointer)
        print(json.dumps(dict(directory=str(directory), **metadata), ensure_ascii=False))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
