"""One-shot stopped global localization. No velocity or posture publisher."""
from project_config import map_path
import argparse
from collections import deque
import fcntl
import json
import math
from pathlib import Path
import signal
import threading
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.srv import GetState
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_srvs.srv import Empty, Trigger
from tf2_ros import Buffer, TransformListener

from localization_validation import amcl_confirmed, select_consistent_pose, stationary_poses
from scan_map_match import Matcher

ROOT = Path(__file__).resolve().parent


def run(check_only=False):
    cancelled = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: cancelled.set())
    rclpy.init()
    node = rclpy.create_node('voice_current_position_localization')
    scans, odoms, poses = deque(maxlen=60), deque(maxlen=600), deque(maxlen=30)
    lock = threading.RLock()
    deadline = time.monotonic()+35
    anchor_time = None

    def stamp(msg):
        return msg.header.stamp.sec+msg.header.stamp.nanosec/1e9

    def scan(msg):
        if msg.header.frame_id == 'nav_scan' and -.05 <= time.time()-stamp(msg) < .7:
            with lock:
                scans.append(msg)

    def odom(msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        with lock:
            odoms.append((stamp(msg), p.x, p.y, 2*math.atan2(q.z, q.w)))

    def amcl(msg):
        with lock:
            poses.append((time.monotonic(), msg))

    subscriptions = [node.create_subscription(LaserScan, '/scan', scan, qos_profile_sensor_data),
                     node.create_subscription(Odometry, '/body_odom', odom, 10),
                     node.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', amcl, 10)]
    publisher = node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
    stop = node.create_client(Trigger, '/stop_navigation')
    state = node.create_client(GetState, '/amcl/get_state')
    refresh = node.create_client(Empty, '/request_nomotion_update')
    buffer = Buffer()
    listener = TransformListener(buffer, node)

    def spin():
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            pass

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()

    def guard(check_stationary=False):
        if cancelled.is_set():
            raise RuntimeError('定位任务已取消')
        if time.monotonic() > deadline:
            raise TimeoutError('重新定位超时')
        bridge = json.loads((ROOT/'velocity_bridge_status.json').read_text())
        if not -.05 <= time.time()-bridge['updated'] < 3:
            raise RuntimeError('停车桥状态过期')
        if bridge.get('goal_id') is not None or any(not math.isfinite(bridge[k]) or abs(bridge[k]) >= .001 for k in ('x', 'y', 'w')):
            raise RuntimeError('尚未锁零停车')
        if check_stationary:
            with lock:
                samples = [p for p in odoms if anchor_time is None or p[0] >= anchor_time]
            if not stationary_poses(samples, time.time()):
                diagnostic = {'samples': len(samples)}
                if samples:
                    diagnostic.update(age_s=time.time()-samples[-1][0],
                                      displacement_m=max(math.hypot(p[1]-samples[0][1], p[2]-samples[0][2]) for p in samples),
                                      max_stamp_gap_s=max((b[0]-a[0] for a,b in zip(samples,samples[1:])), default=0),
                                      min_stamp_gap_s=min((b[0]-a[0] for a,b in zip(samples,samples[1:])), default=0))
                raise RuntimeError('机身位姿变化或里程计过期，请停稳后重新定位：'+json.dumps(diagnostic))

    def call(client, request, timeout=4):
        if not client.wait_for_service(timeout_sec=timeout):
            raise RuntimeError('定位或停车服务不可用')
        future = client.call_async(request)
        end = time.monotonic()+timeout
        while not future.done():
            if cancelled.is_set() or time.monotonic() > min(deadline, end):
                raise TimeoutError('定位服务超时或任务已取消')
            time.sleep(.02)
        return future.result()

    try:
        result = call(stop, Trigger.Request())
        if result is None or not result.success:
            raise RuntimeError('未能确认停车')
        if call(state, GetState.Request()).current_state.id != 3:
            raise RuntimeError('AMCL未激活')
        collect_until = time.monotonic()+6
        while True:
            guard()
            with lock:
                ready = len(scans) >= 12 and stationary_poses(list(odoms), time.time())
            if ready:
                break
            if time.monotonic() > collect_until:
                raise RuntimeError('新鲜扫描不足或机身尚未停稳')
            time.sleep(.05)
        with lock:
            frames = [scans[-11], scans[-6], scans[-1]]
            anchor_time = odoms[0][0]
        matcher = Matcher(map_path('map.yaml'))
        # A recently verified manual initialization is a prior, not a global hypothesis.
        # Never reuse it after appreciable displacement, heading change or expiry.
        if not check_only:
            try:
                evidence = json.loads((ROOT/'manual_localization_verification.json').read_text())
                if evidence.get('verified') and 0 <= time.time()-evidence['updated'] < 600:
                    if refresh.service_is_ready():
                        call(refresh, Empty.Request())
                        time.sleep(.3)
                    guard(True)
                    with lock:
                        record = poses[-1] if poses else None
                    if record and time.monotonic()-record[0] < 2:
                        msg = record[1];p = msg.pose.pose.position;q = msg.pose.pose.orientation
                        pose = [p.x,p.y,2*math.atan2(q.z,q.w)]
                        tf = buffer.lookup_transform('map','nav_body',rclpy.time.Time())
                        tf_age = time.time()-stamp(tf)
                        q = tf.transform.rotation
                        body_yaw = 2*math.atan2(q.z,q.w)
                        prior = evidence['body_map']
                        delta = math.atan2(math.sin(body_yaw-math.radians(prior['yaw_deg'])),
                                           math.cos(body_yaw-math.radians(prior['yaw_deg'])))
                        close = (math.hypot(tf.transform.translation.x-prior['x'],
                                            tf.transform.translation.y-prior['y']) <= .35 and abs(delta) <= .15)
                        scores = [float(matcher.scores(np.array([pose[:2]]),pose[2],
                                  matcher.points(frame.ranges,frame.angle_min,frame.angle_increment))[0]) for frame in frames]
                        cov = [msg.pose.covariance[i] for i in (0,7,35)]
                        print(json.dumps({'manual_prior_diagnostic': {'close':close,'tf_age':tf_age,'scan_scores':scores,'covariance':cov}},ensure_ascii=False),flush=True)
                        if close and -.5 <= tf_age < .7:
                            # Require three distinct, fresh consecutive scans; allow
                            # a short observation window instead of failing on one fluctuation.
                            consecutive=[];last_stamp=None;until=time.monotonic()+5
                            while time.monotonic()<until:
                                guard(True)
                                with lock:
                                    frame=scans[-1] if scans else None
                                    latest=poses[-1] if poses else None
                                if frame is not None and latest and stamp(frame)!=last_stamp and -.05<=time.time()-stamp(frame)<.7:
                                    last_stamp=stamp(frame);msg=latest[1];p=msg.pose.pose.position;q=msg.pose.pose.orientation
                                    pose=[p.x,p.y,2*math.atan2(q.z,q.w)];cov=[msg.pose.covariance[i] for i in (0,7,35)]
                                    score=float(matcher.scores(np.array([pose[:2]]),pose[2],matcher.points(frame.ranges,frame.angle_min,frame.angle_increment))[0])
                                    current=buffer.lookup_transform('map','nav_body',rclpy.time.Time());q=current.transform.rotation
                                    angle=2*math.atan2(q.z,q.w)-math.radians(prior['yaw_deg'])
                                    close_now=(math.hypot(current.transform.translation.x-prior['x'],current.transform.translation.y-prior['y'])<=.35
                                               and abs(math.atan2(math.sin(angle),math.cos(angle)))<=.15)
                                    fresh=(-.5<=time.time()-stamp(current)<.7 and time.monotonic()-latest[0]<2)
                                    valid=close_now and fresh and amcl_confirmed(dict(x=pose[0],y=pose[1],yaw=pose[2]),pose,cov,score)
                                    consecutive=consecutive+[score] if valid else []
                                    if len(consecutive)>=3:
                                        guard(True)
                                        return dict(success=True,verified=True,mode='verified_manual_prior',published_initialpose=False,
                                                    amcl_pose=pose,covariance=cov,scan_scores=consecutive)
                                time.sleep(.05)
            except (OSError,ValueError,KeyError,TypeError):
                pass
        reports = []
        for frame in frames:
            guard(True)
            points = matcher.points(frame.ranges, frame.angle_min, frame.angle_increment)
            reports.append(matcher.search(points))
        candidate = select_consistent_pose(reports)
        guard(True)
        if check_only:
            return dict(success=False, candidate_valid=True, published_initialpose=False,
                        verified=False, candidate=candidate, hypotheses=[h[:2] for h in reports])
        if not publisher.get_subscription_count():
            raise RuntimeError('没有初始定位订阅者')
        initial = PoseWithCovarianceStamped()
        initial.header.frame_id = 'map'
        initial.header.stamp = node.get_clock().now().to_msg()
        initial.pose.pose.position.x, initial.pose.pose.position.y = candidate['x'], candidate['y']
        initial.pose.pose.orientation.z = math.sin(candidate['yaw']/2)
        initial.pose.pose.orientation.w = math.cos(candidate['yaw']/2)
        initial.pose.covariance[0] = initial.pose.covariance[7] = .09
        initial.pose.covariance[35] = .03
        guard(True)
        published_at = time.monotonic()
        publisher.publish(initial)
        verify_until = min(deadline, time.monotonic()+10)
        next_refresh = 0.
        while time.monotonic() < verify_until:
            guard(True)
            now = time.monotonic()
            if now >= next_refresh and refresh.service_is_ready():
                refresh.call_async(Empty.Request())
                next_refresh = now+1
            with lock:
                pose_record = poses[-1] if poses else None
                frame = scans[-1] if scans else None
            if pose_record and pose_record[0] > published_at and frame is not None and time.time()-stamp(frame) < .7:
                msg = pose_record[1]
                p, q = msg.pose.pose.position, msg.pose.pose.orientation
                pose = [p.x, p.y, 2*math.atan2(q.z, q.w)]
                cov = msg.pose.covariance
                points = matcher.points(frame.ranges, frame.angle_min, frame.angle_increment)
                score = float(matcher.scores(np.array([pose[:2]]), pose[2], points)[0])
                try:
                    tf = buffer.lookup_transform('map', 'nav_base', rclpy.time.Time())
                    age = time.time()-stamp(tf)
                    tp, tq = tf.transform.translation, tf.transform.rotation
                    tf_pose = [tp.x, tp.y, 2*math.atan2(tq.z, tq.w)]
                    valid = -.5 <= age < .7 and amcl_confirmed(candidate, tf_pose, [cov[0], cov[7], cov[35]], score)
                except Exception:
                    valid = False
                if valid and amcl_confirmed(candidate, pose, [cov[0], cov[7], cov[35]], score):
                    guard(True)
                    return dict(success=True, verified=True, published_initialpose=True,
                                candidate=candidate, amcl_pose=pose, scan_score=score,
                                covariance=[cov[0], cov[7], cov[35]], hypotheses=[h[:2] for h in reports])
            time.sleep(.05)
        raise RuntimeError('初始位姿已提交，但AMCL或实时TF未通过定位确认')
    finally:
        rclpy.try_shutdown()
        thread.join(timeout=2)
        node.destroy_node()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    started = time.time()
    with (ROOT/'runtime_logs/voice_relocalization.lock').open('w') as single:
        try:
            fcntl.flock(single, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run(args.check_only)
        except Exception as exc:
            result = dict(success=False, verified=False, error=str(exc))
    result.update(updated=time.time(), started=started, motion_sent=False)
    if result.get('success') is True and result.get('verified') is True:
        with (ROOT/'verified_localizations.jsonl').open('a') as journal:
            journal.write(json.dumps(result,ensure_ascii=False)+'\n')
        import sys
        sys.path.insert(0,str(ROOT.parent/'voice_navigation'))
        from home_target import record_verified_home
        try:
            result['home_point']=record_verified_home(ROOT,result)
        except (OSError,ValueError,KeyError) as exc:
            result['home_record_error']=str(exc)
    path = ROOT/'voice_localization_status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temp.replace(path)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get('success') or (args.check_only and result.get('candidate_valid')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
