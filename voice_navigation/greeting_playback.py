"""Play the greeting clip only after native feedback confirms greeting entry."""
import json
import queue
import subprocess
import threading
import time


class GreetingCancelled(RuntimeError):
    pass


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def run_greeting(command, audio_command, is_current, speaking, report, timeout=35):
    action = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines = queue.Queue()
    output = []
    audio = None
    entered = False
    audio_reported = False
    deadline = time.monotonic()+timeout

    def read():
        try:
            for line in action.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    eof = False

    def check():
        if not is_current():
            raise GreetingCancelled('打招呼任务已取消')
        if time.monotonic() > deadline:
            raise subprocess.TimeoutExpired(command, timeout, output=''.join(output))

    def audio_result():
        nonlocal audio_reported
        if audio is not None and audio.poll() is not None and not audio_reported:
            audio_reported = True
            text, _ = audio.communicate()
            speaking(False)
            if audio.returncode:
                report(event='greeting_reply_failed', error=text.strip() or '打招呼语音播放失败')
            else:
                report(event='greeting_reply_finished')

    try:
        while action.poll() is None or not eof:
            check()
            try:
                line = lines.get(timeout=.05)
            except queue.Empty:
                audio_result()
                continue
            if line is None:
                eof = True
                continue
            output.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                event = {}
            if (isinstance(event, dict) and event.get('action') == 'greet'
                    and event.get('entered_greet') is True and 'returned_to_stand' not in event
                    and not entered):
                entered = True
                check()
                # A delayed final transcript must not start speech after the action.
                if action.poll() is None:
                    speaking(True)
                    try:
                        audio = subprocess.Popen(audio_command, stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                        report(event='greeting_reply_started')
                    except OSError as exc:
                        speaking(False)
                        report(event='greeting_reply_failed', error=str(exc))
            audio_result()
        if action.returncode:
            raise subprocess.CalledProcessError(action.returncode, command, output=''.join(output))
        if not entered:
            raise RuntimeError('未确认进入打招呼状态，不播放语音')
        while audio is not None and audio.poll() is None:
            check()
            time.sleep(.03)
        audio_result()
        return subprocess.CompletedProcess(command, action.returncode, ''.join(output), '')
    finally:
        stop_process(audio)
        stop_process(action)
        speaking(False)
        reader.join(timeout=1)
        action.stdout.close()
        if audio is not None and audio.stdout is not None:
            audio.stdout.close()
