"""Cancelable voice adapter for the existing stopped localization pipeline."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from audio_transport import playback_command

ROOT = Path(__file__).resolve().parent


def verified_result(returncode, stdout):
    for line in reversed(stdout.splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict):
            return bool(returncode == 0 and result.get('success') is True
                        and result.get('verified') is True), result
    return False, {'error': '定位程序没有返回有效结果'}


class VoiceRelocalizer:
    def __init__(self, navigator, report):
        self.nav = navigator
        self.report = report
        self.busy = False
        self.speaking = False
        self.recognition_epoch = 0
        self.lock = threading.RLock()
        self.cancelled = None
        self.thread = None

    def start(self):
        with self.lock:
            if self.busy:
                self.report(event='rejected', reason='正在重新定位，请稍候；说停止可取消')
                return
            self.busy = True
            self.cancelled = threading.Event()
            self.thread = threading.Thread(target=self._execute, args=(self.cancelled,), daemon=True)
            self.thread.start()

    def cancel(self):
        with self.lock:
            if self.cancelled is not None:
                self.cancelled.set()

    def _run_command(self, command, timeout, cancelled):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic()+timeout
        try:
            while True:
                if cancelled.is_set():
                    raise RuntimeError('定位任务已取消')
                if time.monotonic() > deadline:
                    raise TimeoutError('定位或播报超时')
                try:
                    stdout, stderr = process.communicate(timeout=.1)
                    return process.returncode, stdout, stderr
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()

    def _execute(self, cancelled):
        success, detail = False, {}
        try:
            self.report(event='localization_started', message='正在定位当前位置，保持趴稳')
            try:
                if self.nav.posture_busy:
                    raise RuntimeError('姿态动作尚未完成，请趴稳后重新定位')
                script = ROOT.parent/'navigation_localization/voice_relocalize.py'
                code, stdout, stderr = self._run_command([sys.executable, str(script)], 40, cancelled)
                success, detail = verified_result(code, stdout)
                if not success and stderr:
                    detail['stderr'] = stderr[-2000:]
            except Exception as exc:
                detail = {'error': str(exc)}
            if cancelled.is_set():
                self.report(event='localization_cancelled', message='定位已取消，保持停车')
                return
            reply = '已定位' if success else '请重新定位'
            self.report(event='localization_result', success=success, reply=reply, detail=detail)
            self.speaking = True
            self.recognition_epoch += 1
            try:
                filename = 'localization_success.wav' if success else 'localization_failure.wav'
                code, _, stderr = self._run_command(playback_command(False, ROOT/'audio', filename), 20, cancelled)
                if code:
                    raise RuntimeError(stderr.strip() or '播报失败')
            except Exception as exc:
                self.report(event='localization_reply_failed', error=str(exc))
            finally:
                self.speaking = False
                self.recognition_epoch += 1
        finally:
            with self.lock:
                self.busy = False

    def close(self):
        self.cancel()
        if self.thread:
            self.thread.join(timeout=3)
