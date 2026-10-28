"""Initialize AMCL once from fresh, stationary scans; never replace manual poses."""
import json
import math
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.srv import GetState
from tf2_ros import Buffer, TransformListener
from scan_map_match import Matcher, angle_delta


class AutoLocalization(Node):
    def __init__(self):
        super().__init__('automatic_map_localization')
        self.root = Path(__file__).parent
        self.matcher = Matcher(self.root/'map.yaml')
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.publisher = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
        self.amcl_state = self.create_client(GetState, '/amcl/get_state')
        self.state_future = None
        self.amcl_active = False
        self.state_checked = 0.
        self.create_subscription(LaserScan, '/scan', self.scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.odometry, qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, '/initialpose', self.manual, 10)
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.scans = []
        self.pose = None
        self.odom_time = 0.
        self.anchor = None
        self.generation = 0
        self.finished = False
        self.next_attempt = 0.
        self.create_timer(.25, self.tick)
        self.report('waiting', '等待实时雷达和静止里程计')

    def report(self, state, message, **extra):
        report = dict(state=state, message=message, updated=time.time(), **extra)
        domain = os.environ.get('ROS_DOMAIN_ID', '0')
        filename = 'auto_localization_status.json' if domain == '93' else f'auto_localization_status_domain_{domain}.json'
        path = self.root/filename
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        temp.replace(path)
        self.get_logger().info(message)

    def manual(self, msg):
        if not self.finished:
            self.finished = True
            self.generation += 1
            p, q = msg.pose.pose.position, msg.pose.pose.orientation
            self.report('manual', '已收到手动初始位姿，自动定位退出',
                        initial_pose={'x': p.x, 'y': p.y, 'yaw': 2*math.atan2(q.z,q.w),
                                      'body_frame': False})

    def odometry(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        self.pose = (p.x, p.y, 2*math.atan2(q.z, q.w))
        self.odom_time = time.monotonic()
        if self.anchor is not None and (math.hypot(p.x-self.anchor[0],p.y-self.anchor[1]) > .05
                                      or abs(angle_delta(self.pose[2],self.anchor[2])) > .04):
            self.generation += 1
            self.scans.clear()
            self.anchor = self.pose

    def scan(self, msg):
        if self.finished or self.pose is None or time.monotonic()-self.odom_time > .7:
            return
        age = (self.get_clock().now().nanoseconds-msg.header.stamp.sec*10**9-msg.header.stamp.nanosec)/1e9
        if not -.1 <= age <= .7 or msg.header.frame_id != 'nav_scan':
            return
        if self.anchor is None:
            self.anchor = self.pose
        now = time.monotonic()
        if self.state_future is not None and self.state_future.done():
            result = self.state_future.result()
            self.amcl_active = result is not None and result.current_state.id == 3
            self.state_future = None
        if self.state_future is None and now-self.state_checked > 1. and self.amcl_state.service_is_ready():
            self.state_future = self.amcl_state.call_async(GetState.Request())
            self.state_checked = now
        if self.scans and now-self.scans[-1][0] < .6:
            return
        try:
            points = self.matcher.points(msg.ranges, msg.angle_min, msg.angle_increment)
        except ValueError:
            return
        self.scans.append((now,points))
        self.scans = self.scans[-3:]

    def match(self, scans):
        hypotheses = self.matcher.search(scans[-1])
        if not self.matcher.confident(hypotheses):
            return hypotheses, False
        best = hypotheses[0]
        # Confirm the same hypothesis against two additional independent frames.
        position = np.array([[best['x'],best['y']]])
        scores = [float(self.matcher.scores(position,best['yaw'],p)[0]) for p in scans]
        return hypotheses, min(scores) >= .70 and max(scores)-min(scores) <= .10

    def tick(self):
        if self.finished:
            return
        # An existing live localization or RViz pose takes precedence.
        if self.buffer.can_transform('map','nav_base',rclpy.time.Time()):
            tf = self.buffer.lookup_transform('map','nav_base',rclpy.time.Time())
            p, q = tf.transform.translation, tf.transform.rotation
            self.finished = True
            self.report('existing', '已有定位，保留当前位姿',
                        initial_pose={'x': p.x, 'y': p.y, 'yaw': 2*math.atan2(q.z,q.w),
                                      'body_frame': False})
            return
        now = time.monotonic()
        if self.future is not None:
            if not self.future.done():
                return
            future, self.future = self.future, None
            try:
                hypotheses, accepted = future.result()
            except Exception as error:
                self.report('error', str(error))
                self.next_attempt = now+10
                return
            fresh = (self.scans and now-self.scans[-1][0] < .7 and now-self.odom_time < .7)
            if self.search_generation != self.generation or not fresh:
                self.report('waiting', '匹配期间发生移动或输入中断，重新采集')
            elif not accepted:
                self.report('ambiguous', '地图匹配不够明确，保持等待；可用 2D Pose Estimate 手动定位', hypotheses=hypotheses[:6])
            elif not self.amcl_active:
                self.report('waiting', '匹配已完成，等待 AMCL 激活后重新确认扫描')
            elif self.publisher.get_subscription_count():
                best = hypotheses[0]
                msg = PoseWithCovarianceStamped()
                msg.header.frame_id = 'map'
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.pose.pose.position.x, msg.pose.pose.position.y = best['x'], best['y']
                msg.pose.pose.orientation.z = math.sin(best['yaw']/2)
                msg.pose.pose.orientation.w = math.cos(best['yaw']/2)
                msg.pose.covariance[0] = msg.pose.covariance[7] = .09
                msg.pose.covariance[35] = .03
                self.finished = True
                self.publisher.publish(msg)
                self.report('initialized', '已根据雷达与地图自动设置 AMCL 初始位姿', hypotheses=hypotheses[:6])
            self.next_attempt = now+10
            return
        if now >= self.next_attempt and len(self.scans) == 3 and now-self.scans[-1][0] < .7:
            self.search_generation = self.generation
            self.future = self.worker.submit(self.match, [p.copy() for _,p in self.scans])
            self.report('matching', '正在全地图搜索位置和方向')


def main():
    rclpy.init()
    node = AutoLocalization()
    try:
        rclpy.spin(node)
    finally:
        node.worker.shutdown(wait=True, cancel_futures=True)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
