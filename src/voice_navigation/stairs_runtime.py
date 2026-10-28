"""Voice mission adapter. Actual 3D services must be commissioned separately."""
from project_config import behavior_path, config_path
import json
import math
import queue
import subprocess
import threading
import time
from pathlib import Path

from audio_transport import playback_command
from stairs_task import StairsTask
from door_wait_target import approach_target
from door_wait_guard import DoorWaitGuard

ROOT = Path(__file__).parent


class StairsRuntime:
    def __init__(self, navigator, report):
        from rclpy.action import ActionClient
        from std_srvs.srv import Trigger
        self.nav = navigator
        self.report = report
        config = json.loads((config_path('stairs_task_config.json')).read_text())
        self.handoff_only = config.get('handoff_only', False)
        self.wait_only = config.get('first_door_wait_only', False)
        self.machine = StairsTask(stop_at_first_confirmation=self.handoff_only,
                                 first_door_wait_only=self.wait_only)
        from nav_msgs.msg import Odometry
        self.wait_guard = DoorWaitGuard()
        self.odom_subscription = navigator.node.create_subscription(
            Odometry, '/body_odom', self._observe_motion, 10)
        self.queue = queue.Queue()
        self.speaking = False
        self.closed = False
        self.in_3d = False
        self.motion_started = False
        self.recognition_epoch = 0
        self.check_client = navigator.node.create_client(Trigger, '/stairs_mission/check_ready')
        self.switch_client = navigator.node.create_client(Trigger, '/stairs_mission/prepare_3d')
        self.confirm_client = navigator.node.create_client(Trigger, '/stairs_mission/confirm_current_door')
        self.door_clients = {i: navigator.node.create_client(Trigger, f'/stairs_mission/confirm_door_{i}') for i in (1,2)}
        self.stop_3d_client = navigator.node.create_client(Trigger, '/stairs_mission/stop')
        self.client_3d = ActionClient(navigator.node, navigator.action_type, '/stairs_mission/navigate_to_pose')
        self.handoff_check = navigator.node.create_client(Trigger, '/stairs_handoff/check_ready')
        self.handoff_prepare = navigator.node.create_client(Trigger, '/stairs_handoff/prepare')
        self.handoff_stop = navigator.node.create_client(Trigger, '/stairs_handoff/stop')
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    @property
    def active(self):
        return self.machine.active or self.machine.pending is not None

    @property
    def awaiting_confirmation(self):
        return self.machine.awaiting_confirmation

    def _post(self, effects):
        for effect in effects:
            self.queue.put(effect)
        self.recognition_epoch += 1
        self.report(event='stairs_task', **self.machine.snapshot())

    def start(self):
        self._post(self.machine.start())

    def start_passage(self, door, direction):
        if self.wait_only:
            self.report(event='rejected', reason='当前仅支持第一扇门前等待，尚未启用穿门')
            return
        self._post(self.machine.start_passage(door, direction))

    def confirm(self):
        effects = self.machine.confirm()
        if not effects:
            self.report(event='stairs_confirmation_rejected', reason='当前没有等待确认的门，或询问尚未播放完毕')
        self._post(effects)

    def cancel(self, reason='任务取消'):
        self._post(self.machine.cancel(reason))

    def _valid(self, effect):
        return not self.closed and self.machine.pending == effect

    def _wait(self, future, effect, timeout):
        deadline = time.monotonic() + timeout
        while not future.done():
            if not self._valid(effect):
                raise RuntimeError('阶段已取消')
            if time.monotonic() >= deadline:
                raise TimeoutError('阶段反馈超时')
            time.sleep(.02)
        return future.result()

    def _service(self, client, effect, timeout=10):
        from std_srvs.srv import Trigger
        if not client.service_is_ready():
            raise RuntimeError('任务服务未就绪')
        result = self._wait(client.call_async(Trigger.Request()), effect, timeout)
        if not result.success:
            raise RuntimeError(result.message or '任务服务拒绝执行')

    def _preflight(self, effect):
        self.config = json.loads((config_path('stairs_task_config.json')).read_text())
        if getattr(self, 'wait_only', False):
            if self.nav.busy or self.nav.posture_busy:
                raise RuntimeError('已有导航或姿态任务')
            self.in_3d = False
            self.motion_started = False
            self._check_2d()
            if not (ROOT / 'audio/request_open_door.wav').is_file():
                raise RuntimeError('缺少请求开门播报音频')
            return
        if self.handoff_only and not self.machine.passage:
            if self.nav.busy or self.nav.posture_busy:
                raise RuntimeError('已有导航或姿态任务')
            self.in_3d = False
            self.motion_started = False
            self._check_2d()
            for key in ('map_3d_ready', 'request_open_door', 'confirm_door_open'):
                if not (ROOT / 'audio' / (key + '.wav')).exists():
                    raise RuntimeError('缺少播报音频：' + key)
            self._service(self.handoff_check, effect)
            return
        missing = []
        if not self.config['execution_enabled']:
            missing.append('实机执行尚未启用')
        for key, name in [('map_alignment_confirmed', '二维/三维坐标未标定'),
                          ('localization_3d_verified', '三维实时定位未验证'),
                          ('controller_3d_verified', '三维控制链路未验证')]:
            if not self.config[key]:
                missing.append(name)
        if not self.config['door_1']['position_confirmed']:
            missing.append('玻璃门等待位置需现场核对')
        if any(not p['confirmed'] for p in self.config['targets'].values()):
            missing.append('三维停靠坐标需现场核对')
        if self.nav.busy or self.nav.posture_busy:
            missing.append('已有导航或姿态任务')
        if not all(c.service_is_ready() for c in (self.check_client, self.switch_client, self.stop_3d_client, self.confirm_client)) or not self.client_3d.server_is_ready():
            missing.append('三维任务执行后端尚未接入')
        for key in ('request_open_door', 'confirm_door_open', 'permit_door_1_enter', 'permit_door_1_exit', 'permit_door_2_enter', 'permit_door_2_exit'):
            if not (ROOT / 'audio' / (key + '.wav')).exists():
                missing.append('缺少播报音频：' + key)
        if missing:
            raise RuntimeError('；'.join(missing))
        self._service(self.check_client, effect)
        if self.machine.passage:
            self._fresh_tf(self.config['frame_3d'])
            self.in_3d = True
        else:
            self._check_2d()

    def _check_2d(self):
        self.nav.ensure_navigation_ready()
        if not self.nav.client.server_is_ready() or not self.nav.stop_client.service_is_ready():
            raise RuntimeError('二维导航或停止服务未就绪')
        status = json.loads((ROOT.parent / 'navigation_localization/velocity_bridge_status.json').read_text())
        cov = status.get('covariance')
        if not (-.5 <= time.time() - status['updated'] <= 3) or status.get('match', 0) < .45 or not cov or max(cov[:2]) >= .25 or cov[2] >= .09 or status.get('reason') == '运动连接断开':
            raise RuntimeError('二维定位或运动连接未通过检查')
        self._fresh_tf('map')

    def _fresh_tf(self, frame):
        child = 'nav_body' if frame == 'map' else self.config.get('body_frame_3d', 'stairs_body')
        tf = self.nav.buf.lookup_transform(frame, child, self.nav.ros.time.Time())
        age = self.nav.node.get_clock().now().nanoseconds / 1e9 - (tf.header.stamp.sec + tf.header.stamp.nanosec / 1e9)
        if not -self.nav.transform_tolerance <= age < .7:
            raise RuntimeError('定位坐标变换过期')

    def _navigate(self, effect):
        if effect.kind == 'navigate_2d':
            import yaml
            self._check_2d()
            target = approach_target(self.config)
            client, frame = self.nav.client, 'map'
        else:
            if not self.in_3d:
                raise RuntimeError('三维导航尚未准备完成')
            self._service(self.check_client, effect)
            if self.machine.state in ('go_door_2','go_fixed','passage_cross'):
                client = self.door_clients[self.machine.door]
                self._service(client, effect)
            frame = self.config['frame_3d']
            self._fresh_tf(frame)
            target = self.config['targets'][effect.value]
            client = self.client_3d
        goal = self.nav.action_type.Goal()
        if effect.kind == 'navigate_2d':
            goal.behavior_tree = str(behavior_path('navigate_arrival_v2.xml'))
        goal.pose.header.frame_id = frame
        goal.pose.header.stamp = self.nav.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(target['x'])
        goal.pose.pose.position.y = float(target['y'])
        goal.pose.pose.position.z = float(target.get('z', 0))
        goal.pose.pose.orientation.z = math.sin(target['yaw'] / 2)
        goal.pose.pose.orientation.w = math.cos(target['yaw'] / 2)
        self.motion_started = True
        sent = client.send_goal_async(goal)
        # A late acceptance after cancellation must never start a stale goal.
        sent.add_done_callback(lambda f: f.result().cancel_goal_async()
                               if f.result().accepted and not self._valid(effect) else None)
        handle = self._wait(sent, effect, 8)
        if not handle.accepted:
            raise RuntimeError('导航目标被拒绝')
        self.nav.goal = handle
        try:
            result = self._wait(handle.get_result_async(), effect, 180)
            if result.status != 4:
                raise RuntimeError('导航未成功到达：' + str(result.status))
        except Exception:
            handle.cancel_goal_async()
            raise
        finally:
            if self.nav.goal is handle:
                self.nav.goal = None

    def _observe_motion(self, msg):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        v = msg.twist.twist
        self.wait_guard.observe(stamp, v.linear.x, v.linear.y, v.angular.z,
                                time.time(), time.monotonic())

    def _wait_stopped(self, effect, timeout=6):
        deadline = time.monotonic() + timeout
        while self._valid(effect):
            self._check_2d()
            target = approach_target(self.config)
            transform = self.nav.buf.lookup_transform('map', 'nav_body', self.nav.ros.time.Time())
            p, q = transform.transform.translation, transform.transform.rotation
            yaw = 2 * math.atan2(q.z, q.w)
            tolerance = self.config['arrival_tolerance']
            if (math.hypot(p.x - target['x'], p.y - target['y']) > tolerance['position_m']
                    or abs(math.atan2(math.sin(yaw - target['yaw']), math.cos(yaw - target['yaw']))) > tolerance['yaw_rad']):
                raise RuntimeError('停稳后偏离门前等待范围，保持停车，请重新发出下楼指令')
            status = json.loads((ROOT.parent / 'navigation_localization/velocity_bridge_status.json').read_text())
            zero = all(math.isfinite(status.get(k, float('nan'))) and abs(status[k]) < .001
                       for k in ('x', 'y', 'w'))
            if zero and self.wait_guard.ready(time.time(), time.monotonic()):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('尚未收到连续停稳反馈，未播报开门')
            time.sleep(.05)
        raise RuntimeError('门前等待任务已取消')

    def _perform(self, effect):
        if effect.kind == 'check':
            self._preflight(effect)
        elif effect.kind.startswith('navigate_'):
            self._navigate(effect)
        elif effect.kind == 'switch' and self.handoff_only:
            self._service(self.handoff_prepare, effect, 35)
            self.in_3d = True
            self._play_prompt(effect, 'map_3d_ready')
        elif effect.kind == 'switch':
            self._service(self.switch_client, effect)
            self._service(self.check_client, effect)
            self._fresh_tf(self.config['frame_3d'])
            self.in_3d = True
        elif effect.kind == 'stop':
            if self.nav.goal:
                self.nav.goal.cancel_goal_async()
            # Preflight failure must not cancel unrelated navigation or send motion.
            if self.machine.state == 'failed' and not self.motion_started:
                return
            if getattr(self, 'wait_only', False):
                self._service(self.nav.stop_client, effect)
                if self.machine.state == 'stop_1':
                    self._wait_stopped(effect)
            elif self.handoff_only and not self.machine.passage:
                self._service(self.handoff_stop, effect)
                self._service(self.nav.stop_client, effect)
            elif self.in_3d:
                self._service(self.stop_3d_client, effect)
            else:
                self._service(self.nav.stop_client, effect)
        elif effect.kind == 'speak':
            self._play_prompt(effect, effect.value)
        else:
            raise RuntimeError('未知任务阶段')

    def _play_prompt(self, effect, key):
        if getattr(self, 'wait_only', False):
            self._wait_stopped(effect)
        elif self.handoff_only and not self.machine.passage:
            self._check_2d()
            self._service(self.handoff_check, effect)
        if not self._valid(effect):
            raise RuntimeError('阶段已取消')
        self.speaking = True
        self.recognition_epoch += 1
        self.report(event='stairs_prompt', text=self.config['phrases'][key], door=self.machine.door)
        try:
            subprocess.run(playback_command(False, ROOT / 'audio', key + '.wav'), check=True, timeout=12)
        finally:
            self.speaking = False
            self.recognition_epoch += 1

    def _run(self):
        while not self.closed:
            try:
                effect = self.queue.get(timeout=.05)
            except queue.Empty:
                if self.machine.state.endswith('_delay'):
                    effects = self.machine.tick()
                    if effects:
                        self._post(effects)
                continue
            if not self._valid(effect):
                continue
            try:
                self._perform(effect)
            except Exception as exc:
                self._post(self.machine.done(effect.token, False, str(exc)))
            else:
                self._post(self.machine.done(effect.token))

    def close(self):
        self.cancel('语音程序退出')
        deadline = time.monotonic() + 2
        while self.machine.pending is not None and time.monotonic() < deadline:
            time.sleep(.02)
        self.closed = True
        self.worker.join(timeout=1)
