"""Cancellable 2 -> 1 -> 3 -> 4 inspection, using the existing guarded Nav2 bridge."""
import json
import math
from pathlib import Path
import subprocess
import threading
import time
from audio_transport import playback_command
from patrol_routes import path_inside_route
from patrol_detection import load_detector

ROOT = Path(__file__).parent
NAV = ROOT.parent / 'navigation_localization'


class MissionError(RuntimeError):
    def __init__(self, phrase):
        super().__init__(phrase)
        self.phrase = phrase


class Cancelled(RuntimeError):
    pass


class PatrolRuntime:
    def __init__(self, navigator, report):
        from nav_msgs.msg import Odometry, Path as NavPath
        from sensor_msgs.msg import Image
        from rclpy.qos import qos_profile_sensor_data
        self.nav, self.report = navigator, report
        self.active = self.speaking = False
        self.return_corridor = None
        self.return_corridor_started = 0.
        self.recognition_epoch = 0
        self.cancelled = threading.Event()
        self.frame = None
        self.frame_stamp = 0
        self.frame_seq = 0
        self.lock = threading.Lock()
        self.goal = self.audio = None
        self.worker = None
        self.subscription = self.nav.node.create_subscription(Image, '/dog_camera/image_raw', self._image, 1)
        self.path_subscription = self.nav.node.create_subscription(NavPath, '/plan', self._plan, 10)
        self.timer = self.nav.node.create_timer(.1, self._watchdog)
        self.stationary_since = None
        self.odom_stamp = 0.
        self.odom_subscription = self.nav.node.create_subscription(Odometry, '/body_odom', self._odom, qos_profile_sensor_data)
        self.fault = None
        self.sensor_counts = {}
        self.sensor_progress = {}

    def _plan(self, message):
        route = self.return_corridor
        if not self.active or self.cancelled.is_set() or route is None or not message.poses:
            return
        if message.header.stamp.sec+message.header.stamp.nanosec*1e-9 < self.return_corridor_started:
            return
        if message.header.frame_id != 'map' or not path_inside_route(
                [(p.pose.position.x,p.pose.position.y) for p in message.poses], route):
            self.fault = 'planning_error'
            self.cancelled.set()
            self._stop_motion()

    def _odom(self, message):
        stamp = message.header.stamp.sec + message.header.stamp.nanosec*1e-9
        self.odom_stamp = stamp
        velocity = message.twist.twist
        still = (math.isfinite(velocity.linear.x) and math.isfinite(velocity.linear.y)
                 and math.isfinite(velocity.angular.z) and math.hypot(velocity.linear.x, velocity.linear.y) < .03
                 and abs(velocity.angular.z) < .05 and -.05 <= time.time()-stamp < .7)
        if still:
            if self.stationary_since is None:
                self.stationary_since = time.monotonic()
        else:
            self.stationary_since = None

    def _park(self):
        parked = self._stop_motion()
        if parked is None or not self._wait(parked,5).success:
            raise MissionError('planning_error')
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            self._check()
            if (self.stationary_since is not None and time.monotonic()-self.stationary_since >= .6
                    and -.05 <= time.time()-self.odom_stamp < .7):
                return
            time.sleep(.025)
        raise MissionError('planning_error')

    def _image(self, message):
        from cv_bridge import CvBridge
        stamp = message.header.stamp.sec + message.header.stamp.nanosec*1e-9
        if not -.05 <= time.time()-stamp < .7:
            return
        try:
            frame = CvBridge().imgmsg_to_cv2(message, 'bgr8')
        except Exception:
            return
        with self.lock:
            self.frame, self.frame_stamp = frame, stamp
            self.frame_seq += 1

    def _health(self):
        try:
            bridge = json.loads((NAV/'bridge_status.json').read_text())
            motion = json.loads((NAV/'velocity_bridge_status.json').read_text())
            for key in ('1', '2'):
                count = bridge.get('received', {}).get(key, 0)
                if count and self.sensor_counts.get(key) != count:
                    self.sensor_counts[key] = count
                    self.sensor_progress[key] = time.monotonic()
                if time.monotonic()-self.sensor_progress.get(key, 0) > 1.5:
                    return 'camera_error'
            if time.time()-(NAV/'robot_motion_status.json').stat().st_mtime > 2:
                return 'camera_error'
            if (time.time()-bridge['updated'] > 2 or bridge.get('connection') != 'connected'
                or max(bridge.get('sensor_age_s', {'0':99}).values()) > .7
                or time.time()-motion['updated'] > 2 or motion.get('reason') == '运动连接断开'):
                return 'camera_error'
            if time.time()-self.frame_stamp > .7:
                return 'camera_error'
        except (OSError, ValueError, KeyError, TypeError):
            return 'camera_error'
        return None

    def _watchdog(self):
        if self.active and not self.cancelled.is_set():
            fault = self._health()
            if fault:
                self.fault = fault
                self._stop_motion()
                self.cancelled.set()

    def _stop_motion(self):
        if self.goal is not None:
            try:
                self.goal.cancel_goal_async()
            except Exception as exc:
                self.goal = None
                self.report(event='goal_cancel_unavailable', detail=str(exc))
        # A stale action handle must never prevent the independent stop service.
        try:
            if self.nav.stop_client.service_is_ready():
                from std_srvs.srv import Trigger
                return self.nav.stop_client.call_async(Trigger.Request())
        except Exception as exc:
            self.report(event='stop_service_unavailable', detail=str(exc))

    def cancel(self):
        self.fault = None
        self.cancelled.set()
        self._stop_motion()
        if self.audio and self.audio.poll() is None:
            self.audio.terminate()

    def close(self):
        self.cancel()
        if self.worker:
            self.worker.join(timeout=3)

    def _check(self):
        if self.cancelled.is_set():
            if self.fault:
                raise MissionError(self.fault)
            raise Cancelled()
        fault = self._health()
        if fault:
            raise MissionError(fault)

    def _wait(self, future, timeout, late_goal=False):
        deadline = time.monotonic()+timeout
        while True:
            try:
                self._check()
                if future.done():
                    return future.result()
                if time.monotonic() > deadline:
                    raise MissionError('planning_error')
            except (Cancelled, MissionError):
                if late_goal:
                    def cancel_late(done):
                        try:
                            goal = done.result()
                            if goal.accepted:
                                goal.cancel_goal_async()
                        except Exception:
                            pass
                    future.add_done_callback(cancel_late)
                raise
            time.sleep(.025)

    def pose(self):
        tf = self.nav.buf.lookup_transform('map', 'nav_body', self.nav.ros.time.Time())
        age = time.time()-tf.header.stamp.sec-tf.header.stamp.nanosec*1e-9
        if not -self.nav.transform_tolerance <= age < .7:
            raise MissionError('planning_error')
        q = tf.transform.rotation
        return dict(x=tf.transform.translation.x, y=tf.transform.translation.y,
                    yaw=2*math.atan2(q.z,q.w))

    def _navigate(self, point, position_only=False):
        self._check()
        self.nav.ensure_navigation_ready()
        status = json.loads((NAV/'velocity_bridge_status.json').read_text())
        cov = status.get('covariance')
        if not cov or max(cov[:2]) >= .25 or cov[2] >= .09 or status.get('match', 0) < .45:
            raise MissionError('planning_error')
        goal = self.nav.action_type.Goal()
        goal.behavior_tree = str(NAV/'navigate_arrival_v2.xml')
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.nav.node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = float(point['x']), float(point['y'])
        goal.pose.pose.orientation.z = math.sin(point['yaw']/2)
        goal.pose.pose.orientation.w = math.cos(point['yaw']/2)
        self._check()
        self.goal = self._wait(self.nav.client.send_goal_async(goal), 10, late_goal=True)
        self._check()
        if not self.goal.accepted:
            raise MissionError('planning_error')
        # Check the requested target directly, independently of the /plan monitor.
        import sys
        if str(NAV) not in sys.path:
            sys.path.append(str(NAV))
        from terminal_guard import TerminalRotationGuard
        import yaml
        control = yaml.safe_load((NAV/'motion.yaml').read_text())['controller_server']['ros__parameters']
        checker = control['general_goal_checker']
        guard = TerminalRotationGuard(checker['xy_goal_tolerance'], checker['yaw_goal_tolerance'])
        pending = self.goal.get_result_async()
        deadline = time.monotonic()+self.config['navigation_timeout_seconds']
        while not pending.done():
            self._check()
            actual = self.pose()
            status = json.loads((NAV/'velocity_bridge_status.json').read_text())
            if not -.05 <= time.time()-status['updated'] < 2:
                raise MissionError('planning_error')
            distance = math.hypot(actual['x']-point['x'], actual['y']-point['y'])
            error = math.atan2(math.sin(point['yaw']-actual['yaw']), math.cos(point['yaw']-actual['yaw']))
            if position_only and distance <= checker['xy_goal_tolerance']:
                self._park()
                actual = self.pose()
                if math.hypot(actual['x']-point['x'],actual['y']-point['y']) > checker['xy_goal_tolerance']:
                    raise MissionError('planning_error')
                self.goal = None
                return
            failure = guard.update('patrol_goal', distance, error, status['x'], status['w'], time.monotonic())
            if failure:
                self.report(event='patrol_rotation_failed', reason=failure, distance_m=distance)
                raise MissionError('planning_error')
            if time.monotonic() > deadline:
                raise MissionError('planning_error')
            self.cancelled.wait(.05)
        self._check()
        result = pending.result()
        if result.status != 4:
            raise MissionError('planning_error')
        self.goal = None
        actual = self.pose()
        if math.hypot(actual['x']-point['x'],actual['y']-point['y']) > .55:
            raise MissionError('planning_error')
        if not position_only and abs(math.atan2(math.sin(actual['yaw']-point['yaw']),math.cos(actual['yaw']-point['yaw']))) > .30:
            raise MissionError('planning_error')
        self._park()

    def _arrival_limits(self):
        limits = self.config.get('arrival_validation', {})
        return float(limits.get('position_m', 1.0)), math.radians(float(limits.get('yaw_degrees', 15.0)))

    def _visit(self, point):
        """Separate position arrival from collision-checked heading alignment."""
        self._navigate(point, position_only=True)
        self._check()
        actual = self.pose()
        delta = math.atan2(math.sin(point['yaw']-actual['yaw']),
                           math.cos(point['yaw']-actual['yaw']))
        self.report(event='patrol_aligning', target_map_yaw_deg=math.degrees(point['yaw']),
                    relative_degrees=math.degrees(delta))
        position_limit, yaw_limit = self._arrival_limits()
        if abs(delta) > yaw_limit:
            self._turn_around(delta, tolerance=yaw_limit)
        self._check()
        actual = self.pose()
        import yaml
        checker = yaml.safe_load((NAV/'motion.yaml').read_text())['controller_server']['ros__parameters']['general_goal_checker']
        distance = math.hypot(actual['x']-point['x'], actual['y']-point['y'])
        error = math.atan2(math.sin(point['yaw']-actual['yaw']),math.cos(point['yaw']-actual['yaw']))
        if distance > position_limit or abs(error) > yaw_limit:
            self.report(event='patrol_alignment_failed', distance_m=distance, yaw_error_deg=math.degrees(error))
            raise MissionError('planning_error')
        # The dwell starts only after verified position, heading, and measured standstill.
        self._park()

    def _say(self, phrase, fault=False):
        if self.cancelled.is_set() and self.fault is None:
            raise Cancelled()
        if not fault:
            self._check()
        self.speaking = True
        self.recognition_epoch += 1
        self.report(event='patrol_speaking', phrase=phrase)
        try:
            self.audio = subprocess.Popen(playback_command(False, ROOT/'audio', phrase+'.wav'),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline = time.monotonic()+15
            while self.audio.poll() is None:
                if self.cancelled.is_set() and self.fault is None:
                    raise Cancelled()
                if not fault:
                    self._check()
                if time.monotonic() > deadline:
                    raise MissionError('camera_error')
                time.sleep(.05)
            if self.audio.returncode and not fault:
                raise MissionError('camera_error')
        finally:
            if self.audio and self.audio.poll() is None:
                self.audio.terminate()
            self.speaking = False
            self.recognition_epoch += 1

    def _observe(self, kind):
        from patrol_vision import StableDetection
        stable = StableDetection()
        deadline = time.monotonic()+self.config['observation_seconds']
        with self.lock:
            last = self.frame_seq
        while time.monotonic() < deadline:
            self._check()
            with self.lock:
                frame, seq = self.frame, self.frame_seq
            if seq != last and frame is not None:
                last = seq
                try:
                    label, evidence = self.detector.detect(frame, kind)
                except Exception as exc:
                    self.report(event='patrol_detector_failed', detail=str(exc))
                    raise MissionError('sign_error' if kind == 'sign' else 'camera_error') from exc
                self.report(event='patrol_detection', kind=kind, label=label, evidence=evidence)
                confirmed = stable.update(label)
                if confirmed and time.monotonic() <= deadline:
                    return confirmed
            time.sleep(.03)
        self._check()
        return None

    def _turn_around(self, angle=math.pi, tolerance=.30):
        from nav2_msgs.action import Spin
        from rclpy.action import ActionClient
        self._check()
        initial = self.pose()
        spin = ActionClient(self.nav.node, Spin, '/spin')
        try:
            if not spin.wait_for_server(timeout_sec=2):
                raise MissionError('planning_error')
            goal = Spin.Goal()
            goal.target_yaw = angle
            goal.time_allowance.sec = 45
            self._check()
            self.goal = self._wait(spin.send_goal_async(goal),10,late_goal=True)
            if not self.goal.accepted:
                raise MissionError('planning_error')
            result = self._wait(self.goal.get_result_async(),50)
            if result.status != 4:
                raise MissionError('planning_error')
            self.goal = None
            self._park()
            actual = self.pose()
            error = actual['yaw']-initial['yaw']-angle
            if (abs(math.atan2(math.sin(error), math.cos(error))) > tolerance
                    or math.hypot(actual['x']-initial['x'],actual['y']-initial['y']) > self._arrival_limits()[0]):
                raise MissionError('planning_error')
        finally:
            # On failure the goal must remain cancellable until the stop request is sent.
            try:
                if self.goal is not None:
                    try:
                        self.goal.cancel_goal_async()
                    except Exception as exc:
                        self.report(event='spin_cancel_unavailable', detail=str(exc))
            finally:
                # Clear before destroying the action client: the handle cannot be reused.
                self.goal = None
                spin.destroy()

    def start_frontdoor(self, point):
        if self.active or (self.worker and self.worker.is_alive()):
            return
        self.config = json.loads((ROOT/'patrol_config.json').read_text())
        self.cancelled = threading.Event()
        self.return_corridor = None
        self.fault = None
        self.active = True
        self.worker = threading.Thread(target=self._frontdoor, args=(dict(point),), daemon=True)
        self.worker.start()

    def _frontdoor(self, point):
        try:
            self._check()
            self.report(event='goal_accepted', reply='好的')
            threading.Thread(target=self.nav.acknowledge, daemon=True).start()
            self.report(event='frontdoor_approaching', point=point)
            self._navigate(point, position_only=True)
            self._check()
            actual = self.pose()
            target_yaw = float(point['yaw'])
            delta = math.atan2(math.sin(target_yaw-actual['yaw']), math.cos(target_yaw-actual['yaw']))
            self.report(event='frontdoor_turning', target_map_yaw_deg=math.degrees(target_yaw),
                        relative_degrees=math.degrees(delta))
            position_limit, yaw_limit = self._arrival_limits()
            if abs(delta) > yaw_limit:
                self._turn_around(delta, tolerance=yaw_limit)
            aligned = self.pose()
            remaining = math.atan2(math.sin(target_yaw-aligned['yaw']), math.cos(target_yaw-aligned['yaw']))
            if (abs(remaining) > yaw_limit or math.hypot(aligned['x']-point['x'],aligned['y']-point['y']) > position_limit):
                raise MissionError('planning_error')
            self._check()
            self.nav.paused = False
            self.nav.save_destination(False)
            self.report(event='navigation_result', status=4, outcome='已到'+point.get('name', '目标点')+'并对齐指定地图方向')
        except Cancelled:
            self.report(event='navigation_result', status=5, outcome='已取消')
        except Exception as exc:
            self.report(event='frontdoor_failed', error=str(exc))
        finally:
            try:
                self._stop_motion()
            finally:
                self.active = False

    def start(self):
        if self.active or (self.worker and self.worker.is_alive()):
            return
        # Capture the origin at the command, never at a later mission stage.
        try:
            self.config = json.loads((ROOT/'patrol_config.json').read_text())
            home = self.pose()
            if self.config.get('mode') != 'navigation_test':
                self.detector = load_detector(self.config.get('vision', {}))
            self.nav.ensure_navigation_ready()
        except Exception as exc:
            self.report(event='rejected', reason='巡检尚未就绪：'+str(exc))
            return
        self.cancelled = threading.Event()
        self.return_corridor = None
        self.fault = None
        self.active = True
        self.worker = threading.Thread(target=self._run, args=(home,),daemon=True)
        self.worker.start()

    def _dwell(self, ident):
        self.report(event='patrol_waiting', point=ident, seconds=5)
        deadline = time.monotonic()+5.
        while time.monotonic() < deadline:
            self._check()
            self.cancelled.wait(min(.05, max(0., deadline-time.monotonic())))
        self._check()

    def _run(self, home):
        try:
            self._check()
            self.report(event='patrol_started', home=home, order=self.config['order'])
            (ROOT/'patrol_session.json').write_text(json.dumps({'home':home,'started':time.time()}))
            for ident in self.config['order']:
                point = self.config['points'][str(ident)]
                override = self.config.get('stop_overrides', {}).get(str(ident))
                if override:
                    import yaml
                    waypoints = yaml.safe_load((NAV/'waypoints.yaml').read_text())['waypoints']
                    point = dict(point)
                    point.update(next(w for w in waypoints if w['id'] == override['waypoint_id']))
                    self.report(event='patrol_stop_override', point=ident, destination=point)
                self.report(event='patrol_navigating', point=ident)
                self._visit(point)
                if self.config.get('mode') == 'navigation_test':
                    self._dwell(ident)
                    if ident == self.config['order'][-1]:
                        self.report(event='patrol_returning', home=home)
                        self._visit(home)
                    continue
                self.report(event='patrol_observing', point=ident)
                label = self._observe(point['kind'])
                if point['kind'] == 'extinguisher':
                    self._say('device_normal' if label else 'device_missing')
                else:
                    if label is None:
                        raise MissionError('sign_error')
                    self.report(event='patrol_sign', sign=label)
                    if label in ('left','right'):
                        route = self.config['return_routes'][label]
                        self.return_corridor = [point]+route
                        self.return_corridor_started = time.time()
                        for index, p in enumerate(route):
                            p = dict(p)
                            following = route[index+1] if index+1 < len(route) else home
                            p['yaw'] = math.atan2(following['y']-p['y'], following['x']-p['x'])
                            self._visit(p)
                        self.return_corridor = None
                    elif label == 'uturn':
                        self._turn_around()
                    self._visit(home)
            self.report(event='patrol_completed')
        except Cancelled:
            self.report(event='patrol_cancelled')
        except Exception as exc:
            self._stop_motion()
            phrase = exc.phrase if isinstance(exc,MissionError) else 'planning_error'
            self.report(event='patrol_failed', phrase=phrase, detail=str(exc))
            if not self.cancelled.is_set() or self.fault:
                try:
                    self._say(phrase, fault=True)
                except Exception:
                    pass
        finally:
            try:
                self._stop_motion()
            finally:
                self.active = False
            self.return_corridor = None
