"""Offline voice commands from AidLux USB mic to existing Nav2 action server."""
from project_config import behavior_path, config_path, map_path
from project_config import remote_file, ssh_command, setting
import argparse
import json
import math
from pathlib import Path
import selectors
import subprocess
import threading
import time
import yaml
import array
import wave
from commands import parse
from wake import WakeSession, WAKE_WORD, WAKE_GRAMMAR
from audio_transport import capture_command, playback_command, REMOTE_SOURCE, REMOTE_SINK
from noise_filter import MicrophoneDenoiser
from recognition import confidence_score
from command_grammar import phrases
from home_target import load_home
from navigation_health import check_navigation_health,NAMES
from stairs_runtime import StairsRuntime
from voice_relocalizer import VoiceRelocalizer
from greeting_playback import GreetingCancelled, run_greeting
from voice_battery import VoiceBatteryQuery
from patrol_runtime import PatrolRuntime

ROOT = Path(__file__).parent
REPORT_LOCK = threading.Lock()


def report(**fields):
    fields['updated'] = time.time()
    fields['event_id'] = time.time_ns()
    with REPORT_LOCK:
        print(json.dumps(fields, ensure_ascii=False), flush=True)
        temporary = ROOT / 'status.tmp'
        temporary.write_text(json.dumps(fields, ensure_ascii=False))
        temporary.replace(ROOT / 'status.json')
        if fields.get('event') == 'waiting_wake':
            (ROOT / 'ui_session.json').write_text(json.dumps(fields, ensure_ascii=False))
        with (ROOT / 'ui_events.jsonl').open('a') as events:
            events.write(json.dumps(fields, ensure_ascii=False) + '\n')


class Navigator:
    def __init__(self, waypoints):
        import rclpy
        from rclpy.action import ActionClient
        from nav2_msgs.action import NavigateToPose
        from std_srvs.srv import Trigger
        from lifecycle_msgs.srv import GetState
        from tf2_ros import Buffer, TransformListener
        rclpy.init()
        self.ros = rclpy
        self.node = rclpy.create_node('voice_navigation')
        self.action_type = NavigateToPose
        self.client = ActionClient(self.node, NavigateToPose, '/navigate_to_pose')
        self.stop_client = self.node.create_client(Trigger, '/stop_navigation')
        self.lifecycle_request = GetState.Request
        self.lifecycle_clients = {name:self.node.create_client(GetState,'/'+name+'/get_state') for name in NAMES}
        self.buf = Buffer()
        self.listener = TransformListener(self.buf, self.node)
        self.points = {w['id']: w for w in waypoints}
        self.busy = False
        self.goal = None
        self.generation = 0
        self.last_destination = None
        self.paused = False
        self.posture_busy = False
        self.posture_speaking = False
        self.posture_recognition_epoch = 0
        state_file = ROOT / 'navigation_session.json'
        if state_file.exists():
            saved = json.loads(state_file.read_text())
            self.last_destination = saved.get('destination')
            self.paused = self.last_destination is not None and saved.get('unfinished', False)
        amcl = yaml.safe_load((config_path('amcl.yaml')).read_text())
        self.transform_tolerance = float(amcl['amcl']['ros__parameters']['transform_tolerance'])
        self.thread = threading.Thread(target=rclpy.spin, args=(self.node,), daemon=True)
        self.thread.start()
        self.stairs = StairsRuntime(self, report)
        self.relocalizer = VoiceRelocalizer(self, report)
        self.battery_query = VoiceBatteryQuery(self, report)
        self.patrol = PatrolRuntime(self, report)

    def dispatch(self, command):
        if command['action'] == 'stop':
            self.patrol.cancel()
        elif self.patrol.active:
            report(event='rejected', reason='巡检进行中，请先说停止')
            return
        if command['action'] == 'patrol_start':
            if self.busy or self.posture_busy or self.stairs.active or self.relocalizer.busy or self.battery_query.busy:
                report(event='rejected', reason='已有任务，请先停止')
            else:
                self.patrol.start()
            return
        if command['action'] == 'stop':
            self.relocalizer.cancel()
            self.battery_query.cancel()
        elif self.battery_query.busy:
            report(event='rejected', reason='正在查询电量，请稍候；说停止可取消')
            return
        elif self.relocalizer.busy:
            report(event='rejected', reason='正在重新定位，请稍候；说停止可取消')
            return
        if command['action'] == 'battery_query':
            if self.posture_busy or self.stairs.speaking:
                report(event='rejected', reason='正在执行动作或播报，请稍后查询电量')
            else:
                self.battery_query.start()
            return
        if command['action'] == 'relocalize':
            self.stairs.cancel('语音重新定位')
            self.generation += 1
            if self.goal:
                self.goal.cancel_goal_async()
            self.relocalizer.start()
            return
        if command['action'] == 'door_passage':
            if self.busy or self.posture_busy or self.stairs.active:
                report(event='rejected', reason='已有任务，请先停止')
            else:
                self.stairs.start_passage(command['door'], command['direction'])
            return
        if command['action'] == 'stairs_approach':
            if self.busy or self.posture_busy or self.stairs.active:
                report(event='rejected', reason='已有导航、下楼准备或姿态任务，请先停止')
            else:
                self.stairs.start()
            return
        if command['action'] == 'confirm_door':
            self.stairs.confirm()
            return
        if command['action'] == 'stop':
            self.stairs.cancel('语音停止')
        elif self.stairs.active:
            report(event='rejected', reason='下楼准备任务进行中，请先说停止')
            return
        if command['action'] in ('stand', 'lie_down', 'greet'):
            if self.posture_busy:
                report(event='rejected', reason='正在处理姿态动作，请稍候')
                return
            self.posture_busy = True
            self.generation += 1
            if self.busy:
                self.paused = True
                self.save_destination(True)
            if self.goal:
                self.goal.cancel_goal_async()
            if not self.stop_client.service_is_ready():
                self.posture_busy = False
                report(event='rejected', reason='停止服务不可用，无法确认导航已停止')
                return
            from std_srvs.srv import Trigger
            future = self.stop_client.call_async(Trigger.Request())
            generation = self.generation
            future.add_done_callback(lambda f: self.posture_stopped(f, command['action'], generation))
            return
        if self.posture_busy and command['action'] != 'stop':
            report(event='rejected', reason='正在处理姿态动作，请稍候')
            return
        if command['action'] == 'stop':
            if self.busy and self.last_destination is not None:
                self.paused = True
                self.save_destination(True)
            # Invalidate pending goal responses; late acceptances are canceled.
            self.generation += 1
            if self.goal:
                self.goal.cancel_goal_async()
            if not self.stop_client.service_is_ready():
                report(event='rejected', reason='停止服务不可用，请检查 velocity_bridge')
                return
            from std_srvs.srv import Trigger
            future = self.stop_client.call_async(Trigger.Request())
            future.add_done_callback(self.stopped)
            return
        if command['action'] == 'resume':
            if not self.paused or self.last_destination is None:
                report(event='rejected', reason='没有暂停的语音目标，请说目的地')
                return
            command = {'action': 'go', 'id': self.last_destination}
        if command['action'] == 'return_home' or command.get('id') == 'home':
            try:
                point = load_home(ROOT.parent / 'navigation_localization')
            except (OSError, ValueError, KeyError, IndexError) as exc:
                report(event='rejected', reason='返回起点不可用：' + str(exc))
                return
        else:
            config = yaml.safe_load((map_path('waypoints.yaml')).read_text())
            self.points = {w['id']: w for w in config['waypoints']}
            point = self.points[command['id']]
            verified = ROOT / 'verified_waypoints.json'
            evidence = json.loads(verified.read_text()) if verified.exists() else {}
            tested = any(all(p.get(k) == point.get(k) for k in ('id', 'x', 'y', 'yaw'))
                         for p in evidence.get('waypoints', []))
            if not point.get('confirmed', False) and not tested:
                report(event='rejected', reason='点位尚未现场确认', destination=point['name'])
                return
        if self.busy:
            report(event='rejected', reason='已有导航任务，请先说停止')
            return
        if not self.stop_client.service_is_ready() or not self.client.server_is_ready():
            report(event='rejected', reason='导航或速度桥接未就绪')
            return
        try:
            self.ensure_navigation_ready()
            status = json.loads((ROOT.parent / 'navigation_localization/velocity_bridge_status.json').read_text())
            covariance = status.get('covariance')
            if (time.time() - status['updated'] > 3 or status.get('match', 0) < .45
                    or not covariance or max(covariance[:2]) >= .25 or covariance[2] >= .09
                    or status.get('reason') == '运动连接断开'):
                raise RuntimeError('运动连接或定位质量不足')
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            report(event='rejected', reason='导航状态检查未通过：' + str(exc))
            return
        try:
            tf = self.buf.lookup_transform('map', 'nav_body', self.ros.time.Time())
            stamp = tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9
            age = self.node.get_clock().now().nanoseconds * 1e-9 - stamp
            # AMCL intentionally postdates map->odom by transform_tolerance.
            if not -self.transform_tolerance <= age < 0.7:
                raise RuntimeError('定位过期')
        except Exception as exc:
            report(event='rejected', reason='等待实时定位：' + str(exc))
            return
        if (point.get('id'), point.get('name')) in ((1, '正门'), (2, '洗手间'), (4, '展示区起点'), (5, '展示区中心'), (6, '窗户')):
            self.last_destination = point['id']
            self.paused = False
            self.save_destination(True)
            self.patrol.start_frontdoor(point)
            return
        goal = self.action_type.Goal()
        goal.behavior_tree = str(behavior_path('navigate_arrival_v2.xml'))
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(point['x'])
        goal.pose.pose.position.y = float(point['y'])
        goal.pose.pose.orientation.z = math.sin(point['yaw'] / 2)
        goal.pose.pose.orientation.w = math.cos(point['yaw'] / 2)
        self.busy = True
        self.last_destination = point['id']
        self.paused = False
        self.save_destination(True)
        generation = self.generation
        future = self.client.send_goal_async(goal)
        future.add_done_callback(lambda f: self.accepted(f, generation))
        report(event='goal_requested', destination=point['name'], id=point['id'])

    def accepted(self, future, generation):
        try:
            self.goal = future.result()
            if not self.goal.accepted:
                self.busy = False
                report(event='goal_rejected')
                return
            if generation != self.generation:
                self.goal.cancel_goal_async()
            else:
                report(event='goal_accepted', reply='好的')
                threading.Thread(target=self.acknowledge, daemon=True).start()
            self.goal.get_result_async().add_done_callback(self.finished)
        except Exception as exc:
            self.busy = False
            report(event='navigation_error', error=str(exc))

    def acknowledge(self):
        try:
            subprocess.run(playback_command(False, ROOT / 'audio', 'okay.wav'),
                           check=True, timeout=8)
        except (OSError, subprocess.SubprocessError) as exc:
            report(event='command_reply_failed', error=str(exc))

    def posture_stopped(self, future, action, generation):
        try:
            if generation != self.generation:
                self.posture_busy = False
                return
            if not future.result().success:
                raise RuntimeError('未能停止导航')
            threading.Thread(target=self.posture_execute, args=(action, generation), daemon=True).start()
        except Exception as exc:
            self.posture_busy = False
            report(event='posture_failed', error=str(exc))

    def posture_execute(self, action, generation):
        try:
            if generation != self.generation:
                return
            command = ssh_command('firefly', ['python3', '-u', remote_file('firefly', 'drivers', 'posture_firefly.py'), action], ros=True)
            if action == 'greet':
                result = run_greeting(command, playback_command(False, ROOT/'audio', 'greet.wav'),
                                      lambda: generation == self.generation,
                                      self.posture_speech_state, report)
            else:
                result = subprocess.run(command, capture_output=True, text=True, timeout=35, check=True)
            message = ('底层已进入打招呼状态并返回站立，需现场确认抬腿动作' if action == 'greet'
                       else '姿态命令已下发，需观察实际动作')
            report(event='posture_sent', action=action, message=message,
                   detail=result.stdout.strip())
        except GreetingCancelled:
            report(event='posture_cancelled', action=action)
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            # Native readiness and action feedback is on stdout; preserve it
            # on failures as well, rather than only the generic SSH exit error.
            detail = '\n'.join(value for value in
                               (getattr(exc, 'stdout', None), getattr(exc, 'stderr', None))
                               if isinstance(value, str))
            report(event='posture_failed', error=str(exc), detail=detail or None)
        finally:
            self.posture_busy = False

    def posture_speech_state(self, speaking):
        if self.posture_speaking != speaking:
            self.posture_speaking = speaking
            self.posture_recognition_epoch += 1

    def save_destination(self, unfinished):
        path = ROOT / 'navigation_session.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'destination': self.last_destination,
                                        'unfinished': unfinished}))
        temporary.replace(path)

    def finished(self, future):
        self.busy = False
        self.goal = None
        try:
            status = future.result().status
            if status == 4:
                self.paused = False
                self.save_destination(False)
            elif status in (5, 6):
                self.paused = True
                self.save_destination(True)
            report(event='navigation_result', status=status,
                   outcome={4: '已到达', 5: '已取消', 6: '导航失败'}.get(status, '未知'))
        except Exception as exc:
            report(event='navigation_error', error=str(exc))

    def stopped(self, future):
        try:
            result = future.result()
            report(event='stop_result', success=result.success, message=result.message)
        except Exception as exc:
            report(event='stop_error', error=str(exc))

    def ensure_navigation_ready(self):
        check_navigation_health(self.lifecycle_clients,self.lifecycle_request)

    def close(self):
        self.generation += 1
        self.patrol.close()
        self.battery_query.close()
        self.relocalizer.close()
        self.stairs.close()
        if self.busy:
            self.dispatch({'action': 'stop'})
            time.sleep(0.5)
        self.ros.try_shutdown()
        self.thread.join(timeout=3)
        self.node.destroy_node()


def audio_chunks(args):
    command = capture_command(args.capture_local, args.source)
    while True:
        process = subprocess.Popen(command, stdout=subprocess.PIPE)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            last = time.monotonic()
            while True:
                events = selector.select(1)
                if not events:
                    if time.monotonic() - last > 3:
                        raise TimeoutError('录音数据超时')
                    continue
                chunk = process.stdout.read1(3200)
                if not chunk:
                    raise EOFError('麦克风连接断开')
                last = time.monotonic()
                yield chunk
        except (EOFError, TimeoutError) as exc:
            report(event='reconnecting', error=str(exc))
            yield None  # Discard recognition state from a broken connection.
        finally:
            selector.close()
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--local', action='store_true', help='Test with this computer microphone and speaker, without SSH or motion')
    modes.add_argument('--computer-mic', action='store_true', help='Capture on this computer, play replies on the robot')
    ap.add_argument('--source', help='PulseAudio microphone name; computer-mic defaults to Newmine, local test to system default')
    ap.add_argument('--execute', action='store_true', help='Send real Nav2 goals; default only recognizes')
    ap.add_argument('--text', help='Test command parsing without microphone or movement')
    ap.add_argument('--wav', type=Path, help='Recognize a prerecorded 16 kHz mono PCM WAV without movement')
    ap.add_argument('--diagnostics', action='store_true', help='Keep the last 10 seconds of live microphone audio locally for diagnosis')
    args = ap.parse_args()
    args.capture_local = args.local or args.computer_mic
    if args.text:
        report(event='parsed', text=args.text, command=parse(args.text))
        return
    if args.wav and args.execute:
        ap.error('录音文件测试不能启用运动')
    if args.local and args.execute:
        ap.error('本机测试不启用运动；实际导航请使用远端模式')
    if args.capture_local and not args.wav:
        sources = subprocess.check_output(['pactl', 'list', 'short', 'sources'], text=True)
        names = [line.split('\t')[1] for line in sources.splitlines() if '\t' in line]
        if not args.source:
            if args.computer_mic:
                microphones = [name for name in names if 'newmine' in name.lower() and not name.endswith('.monitor')]
                if len(microphones) != 1:
                    ap.error('请连接唯一的纽曼 USB 麦克风，或使用 --source 明确指定输入设备；不会自动改用内置麦克风')
                args.source = microphones[0]
            else:
                args.source = subprocess.check_output(['pactl', 'get-default-source'], text=True).strip()
        if args.source not in names or args.source.endswith('.monitor'):
            ap.error('请选择麦克风输入，不能使用扬声器回环：' + args.source)
    elif not args.source:
        args.source = REMOTE_SOURCE
    listener_lock = None
    if not args.wav:
        import fcntl
        listener_lock = (ROOT / 'listener.lock').open('w')
        try:
            fcntl.flock(listener_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            ap.error('语音监听已经运行，请先停止旧进程，避免重复识别和回复')
        import os
        (ROOT / 'listener.pid').write_text(str(os.getpid()))
    if not args.local and not args.wav:
        # Reset robot reply volume on every live voice-control startup.
        try:
            subprocess.run(ssh_command('aidlux', ['pactl', 'set-sink-volume', REMOTE_SINK, '40%'], timeout=5),
                           check=True, timeout=8)
            report(event='reply_volume', percent=40, device=REMOTE_SINK)
        except (OSError, subprocess.SubprocessError) as exc:
            ap.error('无法将机器狗回复音量设置为40%：' + str(exc))
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    model = Model(str(ROOT / 'models/vosk-model-small-cn-0.22'))
    profile = ROOT / ('newmine_noise_profile.npz' if args.capture_local else 'newmine_noise_profile_remote.npz')
    uses_newmine = 'newmine' in args.source.lower()
    if args.computer_mic and not args.wav and uses_newmine and not profile.exists():
        ap.error('缺少纽曼麦克风降噪配置，请恢复 newmine_noise_profile.npz 后再启动')
    denoiser = MicrophoneDenoiser(profile) if profile.exists() and uses_newmine else None
    recognizer = KaldiRecognizer(model, 16000, json.dumps(phrases(model), ensure_ascii=False))
    recognizer.SetWords(True)
    wake_recognizer = KaldiRecognizer(model, 16000, json.dumps(
        WAKE_GRAMMAR + ['停止', '停下',
         '停止 导航', '取消 导航', '确认', '[unk]'], ensure_ascii=False))
    wake_recognizer.SetWords(True)
    transcript_recognizer = KaldiRecognizer(model, 16000)
    transcript_recognizer.SetWords(True)
    general_transcript_recognizer = transcript_recognizer
    navigator = None
    if args.execute:
        import os
        if os.environ.get('ROS_DOMAIN_ID') != '93' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
            ap.error('执行导航需要 ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1；请通过 run.sh 启动')
        config = yaml.safe_load((map_path('waypoints.yaml')).read_text())
        navigator = Navigator(config['waypoints'])
    session = WakeSession()
    report(event='waiting_wake', wake_word=WAKE_WORD, window_seconds=30,
           execute=args.execute, local=args.capture_local, output_robot=not args.local, source=args.source,
           noise_reduction=denoiser is not None)

    def reset_recognition():
        nonlocal transcript_recognizer
        transcript_recognizer = recognizer if session.phase == 'awake' else general_transcript_recognizer
        recognizer.Reset()
        wake_recognizer.Reset()
        general_transcript_recognizer.Reset()
        if denoiser:
            denoiser.reset()

    def active_recognizer():
        return wake_recognizer if session.phase == 'sleeping' else recognizer

    def reply(token):
        success = True
        try:
            if not args.wav:
                subprocess.run(playback_command(args.local, ROOT / 'audio', 'wake_reply.wav'),
                               check=True, timeout=8)
        except (OSError, subprocess.SubprocessError) as exc:
            success = False
            report(event='wake_reply_failed', error=str(exc))
        if session.reply_finished(token, success):
            report(event='awake', reply='我在', window_seconds=30)

    def consume(result):
        text = result.get('text', '')
        if not text:
            return
        command = parse(text)
        words = result.get('result', [])
        confidence = confidence_score(words)
        report(event='recognized', text=text, command=command, confidence=confidence, execute=args.execute)
        if command and command['action'] == 'confirm_door':
            if navigator and navigator.stairs.awaiting_confirmation and not navigator.stairs.speaking:
                navigator.dispatch(command)
            else:
                report(event='stairs_confirmation_rejected', reason='当前没有已询问且待确认的门')
            return
        event, payload = session.feed(text, confidence)
        if event == 'wake':
            report(event='wake_detected', reply='我在')
            if args.wav:
                reply(payload)
            else:
                threading.Thread(target=reply, args=(payload,), daemon=True).start()
            return
        if event == 'needs_wake':
            report(event='needs_wake', reason='请先说'+WAKE_WORD)
            return
        if event != 'command':
            return
        command = payload
        report(event='command_received', command=command,
               awake=session.phase == 'awake', window_seconds=30)
        if navigator:
            navigator.dispatch(command)
        else:
            report(event='command_preview', command=command, execute=False)
            if (args.local or args.computer_mic) and not args.wav:
                try:
                    subprocess.run(playback_command(args.local, ROOT / 'audio', 'okay.wav'),
                                   check=True, timeout=5)
                except (OSError, subprocess.SubprocessError) as exc:
                    report(event='command_reply_failed', error=str(exc))

    chunks = None
    try:
        if args.wav:
            with wave.open(str(args.wav)) as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                    raise ValueError('WAV must be 16 kHz, mono, 16-bit PCM')
                while data := wav.readframes(1600):
                    if denoiser:
                        data = denoiser.feed(data)
                        if not data:
                            continue
                    current = active_recognizer()
                    if current.AcceptWaveform(data):
                        consume(json.loads(current.Result()))
                consume(json.loads(current.FinalResult()))
        else:
            chunks = audio_chunks(args)
            previous_phase = session.phase
            stairs_epoch = navigator.stairs.recognition_epoch + navigator.relocalizer.recognition_epoch + navigator.posture_recognition_epoch + navigator.battery_query.recognition_epoch + navigator.patrol.recognition_epoch if navigator else 0
            recent_audio = bytearray()
            last_meter = time.monotonic()
            last_partial = ''
            last_partial_time = 0
            for data in chunks:
                if data is not None and args.diagnostics:
                    recent_audio.extend(data)
                    if len(recent_audio) > 320000:
                        del recent_audio[:len(recent_audio) - 320000]
                    if time.monotonic() - last_meter >= 5:
                        samples = array.array('h', recent_audio[-32000:])
                        rms = math.sqrt(sum(x*x for x in samples) / max(1, len(samples)))
                        with wave.open(str(ROOT / 'live_mic_diagnostic.wav'), 'wb') as wav:
                            wav.setparams((1, 2, 16000, 0, 'NONE', ''))
                            wav.writeframes(recent_audio)
                        report(event='audio_level', rms=round(rms, 1),
                               peak=max((abs(x) for x in samples), default=0),
                               wake_state=session.phase)
                        last_meter = time.monotonic()
                if session.expire():
                    reset_recognition()
                    report(event='wake_timeout', reason='30 秒内未收到有效指令，请重新唤醒')
                if data is None:
                    if navigator:
                        navigator.relocalizer.cancel()
                        navigator.patrol.cancel()
                        navigator.battery_query.cancel()
                    if navigator and navigator.stairs.active:
                        navigator.dispatch({'action': 'stop'})
                    recent_audio.clear()
                    session.reset()
                    reset_recognition()
                elif navigator and navigator.stairs.recognition_epoch + navigator.relocalizer.recognition_epoch + navigator.posture_recognition_epoch + navigator.battery_query.recognition_epoch + navigator.patrol.recognition_epoch != stairs_epoch:
                    reset_recognition()
                    stairs_epoch = navigator.stairs.recognition_epoch + navigator.relocalizer.recognition_epoch + navigator.posture_recognition_epoch + navigator.battery_query.recognition_epoch + navigator.patrol.recognition_epoch
                elif navigator and (navigator.stairs.speaking or navigator.relocalizer.speaking or navigator.posture_speaking or navigator.battery_query.speaking or navigator.patrol.speaking):
                    # Continue recognizing emergency stop, while rejecting prompt echo.
                    if wake_recognizer.AcceptWaveform(data):
                        value = json.loads(wake_recognizer.Result())
                        if parse(value.get('text', '')) == {'action': 'stop'}:
                            consume(value)
                    recognizer.Reset()
                    general_transcript_recognizer.Reset()
                elif session.phase == 'replying':
                    # Drain microphone audio during the reply to avoid echo/backlog.
                    reset_recognition()
                elif previous_phase != session.phase:
                    reset_recognition()
                else:
                    if denoiser:
                        data = denoiser.feed(data)
                        if not data:
                            continue
                    if transcript_recognizer.AcceptWaveform(data):
                        result = json.loads(transcript_recognizer.Result())
                        if result.get('text'):
                            report(event='transcript', text=result['text'].replace(' ', ''),
                                   confidence=min((w['conf'] for w in result.get('result', [])), default=0))
                        # Use exactly the displayed final recognition for awake
                        # commands, rather than a second independently segmented ASR.
                        if session.phase == 'awake' or (navigator and navigator.stairs.awaiting_confirmation):
                            consume(result)
                        last_partial = ''
                    elif time.monotonic() - last_partial_time >= .25:
                        partial = json.loads(transcript_recognizer.PartialResult()).get('partial', '').replace(' ', '')
                        if partial != last_partial:
                            report(event='transcript_partial', text=partial)
                            last_partial = partial
                        last_partial_time = time.monotonic()
                    if session.phase == 'sleeping':
                        if wake_recognizer.AcceptWaveform(data):
                            consume(json.loads(wake_recognizer.Result()))
                previous_phase = session.phase
    except KeyboardInterrupt:
        report(event='closed')
    finally:
        session.reset()
        if chunks:
            chunks.close()
        if navigator:
            navigator.close()


if __name__ == '__main__':
    main()
