import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from greeting_playback import GreetingCancelled, run_greeting


def python(code):
    return [sys.executable, '-u', '-c', code]


class GreetingPlaybackTests(unittest.TestCase):
    def run_with(self, action, audio, current=lambda: True):
        states, events = [], []
        result = run_greeting(action, audio, current, states.append,
                              lambda **e: events.append(e), timeout=3)
        return result, states, events

    def test_speaks_once_during_acknowledged_action(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'audio'
            done = Path(directory)/'action_done'
            event = json.dumps({'action': 'greet', 'entered_greet': True})
            action = python(f'import time; from pathlib import Path; print({event!r},flush=True); print({event!r},flush=True); time.sleep(.35); Path({str(done)!r}).touch()')
            audio = python(f'from pathlib import Path; p=Path({str(marker)!r}); p.write_text(str(not Path({str(done)!r}).exists()))')
            _, states, events = self.run_with(action, audio)
            self.assertEqual(marker.read_text(), 'True')
            self.assertEqual(sum(e['event'] == 'greeting_reply_started' for e in events), 1)
            self.assertIn(True, states)
            self.assertFalse(states[-1])

    def test_rejected_action_never_plays(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'audio'
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_with(python('import sys; print("charging or not ready"); sys.exit(1)'),
                              python(f'from pathlib import Path; Path({str(marker)!r}).touch()'))
            self.assertFalse(marker.exists())

    def test_final_return_event_is_not_a_start_trigger(self):
        event = json.dumps({'action': 'greet', 'entered_greet': True, 'returned_to_stand': True})
        with self.assertRaisesRegex(RuntimeError, '未确认'):
            self.run_with(python(f'print({event!r})'), python('raise RuntimeError("must not play")'))

    def test_cancel_reaps_both_processes_and_resets_speaking(self):
        current = threading.Event();current.set()
        event = json.dumps({'action': 'greet', 'entered_greet': True})
        timer = threading.Timer(.2, current.clear);timer.start()
        states = []
        try:
            with self.assertRaises(GreetingCancelled):
                run_greeting(python(f'import time; print({event!r},flush=True); time.sleep(2)'),
                             python('import time; time.sleep(2)'), current.is_set, states.append,
                             lambda **e: None, timeout=3)
            self.assertFalse(states[-1])
        finally:
            timer.cancel()

    def test_audio_failure_does_not_repeat_motor_command(self):
        event = json.dumps({'action': 'greet', 'entered_greet': True})
        result, _, events = self.run_with(
            python(f'import time; print({event!r},flush=True); time.sleep(.25)'),
            python('import sys; sys.exit(2)'))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(sum(e['event'] == 'greeting_reply_started' for e in events), 1)
        self.assertEqual(sum(e['event'] == 'greeting_reply_failed' for e in events), 1)

    def test_cancelled_stop_response_does_not_start_stale_posture(self):
        from voice_navigation import Navigator
        from types import SimpleNamespace
        nav = Navigator.__new__(Navigator);nav.generation = 2;nav.posture_busy = True
        nav.posture_stopped(SimpleNamespace(result=lambda: self.fail('stale response')), 'greet', 1)
        self.assertFalse(nav.posture_busy)


if __name__ == '__main__':
    unittest.main()
