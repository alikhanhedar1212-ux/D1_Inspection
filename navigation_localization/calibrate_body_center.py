"""Read-only rotation capture and offline center fitting. Never commands motion.

Capture after the operator confirms that the body rotates without translating.
Fitting prints a proposal; it never modifies the active calibration or map.
"""
import argparse
import json
import math
from pathlib import Path
import time

from body_geometry import fit_rotation_center


def capture(seconds, output):
    import rclpy
    from nav_msgs.msg import Odometry
    from geometry_msgs.msg import Twist
    from tf2_ros import Buffer, TransformListener
    from rclpy.qos import qos_profile_sensor_data
    rclpy.init()
    node = rclpy.create_node('capture_body_rotation_center')
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    rows = []
    command = [0., 0., 0.]

    def commanded(msg):
        command[:] = [msg.linear.x, msg.linear.y, msg.angular.z]

    def odometry(msg):
        stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        if msg.header.frame_id != 'nav_odom' or not -.05 <= time.time()-stamp < .7:
            return
        if rows and stamp <= rows[-1]['odom'][0]:
            return
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        row = dict(odom=[stamp, p.x, p.y, yaw], nav_command=list(command))
        try:
            tf = buffer.lookup_transform('map', 'nav_base', rclpy.time.Time.from_msg(msg.header.stamp))
            p, q = tf.transform.translation, tf.transform.rotation
            row['map'] = [stamp, p.x, p.y,
                          math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))]
        except Exception:
            row['map'] = None
        rows.append(row)

    subscriptions = [node.create_subscription(Odometry, '/odom', odometry, qos_profile_sensor_data),
                     node.create_subscription(Twist, '/nav_cmd_vel', commanded, 10)]
    started = time.time()
    deadline = time.monotonic()+seconds
    try:
        print('采集中：本程序不发布速度。请只按已确认的原地转向操作。', flush=True)
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(dict(started=started, updated=time.time(),
                                         motion_sent=False, rows=rows), ensure_ascii=False, indent=2))
        node.destroy_node()
        rclpy.try_shutdown()
    print(json.dumps(dict(file=str(output), samples=len(rows), motion_sent=False), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', type=float, metavar='SECONDS')
    mode.add_argument('--fit', type=Path, metavar='CAPTURE_JSON')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--stationary-body-confirmed', action='store_true')
    args = parser.parse_args()
    if args.capture is not None:
        if not 3 <= args.capture <= 120:
            parser.error('采集时间应为3～120秒')
        output = args.output or Path(__file__).parent/'runtime_logs'/f'body_rotation_{time.time_ns()}.json'
        capture(args.capture, output)
        return
    if not args.stationary_body_confirmed:
        parser.error('必须由现场确认身体未平移，不能将真实运动拟合成传感器偏移')
    record = json.loads(args.fit.read_text())
    rows = record['rows']
    if any(math.hypot(*row['nav_command'][:2]) > .01 for row in rows):
        raise ValueError('记录包含导航平移指令，不用于原地旋转标定')
    fit = fit_rotation_center([row['odom'] for row in rows])
    result = dict(proposed_offset=fit, calibrated=False, applied=False,
                  requires_map_consistency_review=True, source=str(args.fit))
    mapped = [row['map'] for row in rows if row.get('map') is not None]
    try:
        result['map_fit'] = fit_rotation_center(mapped)
        delta = math.hypot(fit['offset_x_m']-result['map_fit']['offset_x_m'],
                           fit['offset_y_m']-result['map_fit']['offset_y_m'])
        result['map_offset_difference_m'] = delta
        result['map_consistent'] = delta <= .05
    except ValueError as exc:
        result.update(map_consistent=False, map_fit_error=str(exc))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
