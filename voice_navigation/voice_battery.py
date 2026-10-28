"""Read-only, cancellable native battery query with a robot-side spoken reply."""
import json
from pathlib import Path
import threading
import time

from battery_data import battery_reply, validate_sample
from voice_relocalizer import VoiceRelocalizer

ROOT = Path(__file__).resolve().parent


class VoiceBatteryQuery(VoiceRelocalizer):
    def start(self):
        with self.lock:
            if self.busy:
                self.report(event='rejected', reason='正在查询电量，请稍候')
                return
            super().start()

    def _execute(self, cancelled):
        success, percent, detail = False, None, {}
        try:
            self.report(event='battery_query_started')
            try:
                started = time.monotonic()
                command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                           '-o', 'ServerAliveInterval=2', '-o', 'ServerAliveCountMax=2',
                           'firefly', '/home/firefly/rviz_navigation/read_battery_native']
                code, stdout, stderr = self._run_command(command, 12, cancelled)
                if code:
                    raise RuntimeError(stderr.strip() or '未收到实时电池数据')
                sample = None
                for line in reversed(stdout.splitlines()):
                    try:
                        candidate = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(candidate, dict) and candidate.get('source') == 'battery_state':
                        sample = candidate
                        break
                if sample is None:
                    raise ValueError('没有有效的电池读取结果')
                percent = validate_sample(sample, time.monotonic()-started)
                success, detail = True, sample
            except Exception as exc:
                detail = {'error': str(exc)}
            if cancelled.is_set():
                self.report(event='battery_query_cancelled')
                return
            text = battery_reply(percent) if success else '暂时无法读取电量，请稍后再试'
            result = dict(success=success, percent=percent, reply=text, detail=detail, updated=time.time())
            path = ROOT/'battery_status.json'
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            temp.replace(path)
            self.report(event='battery_result', **result)
            self.speaking = True
            self.recognition_epoch += 1
            try:
                command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                           'aidlux', 'python3', '/home/aidlux/voice_navigation/battery_reply.py',
                           str(percent) if success else 'unavailable']
                code, _, stderr = self._run_command(command, 20, cancelled)
                if code:
                    raise RuntimeError(stderr.strip() or '电量播报失败')
                self.report(event='battery_reply_finished')
            except Exception as exc:
                self.report(event='battery_reply_failed', error=str(exc))
            finally:
                self.speaking = False
                self.recognition_epoch += 1
        finally:
            with self.lock:
                self.busy = False
