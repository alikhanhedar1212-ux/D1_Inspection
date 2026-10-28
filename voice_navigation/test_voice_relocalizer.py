import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from commands import parse
from command_grammar import phrases
from voice_relocalizer import VoiceRelocalizer, verified_result
from wake import WakeSession


class VoiceRelocalizerTests(unittest.TestCase):
    def test_exact_phrases_and_negations(self):
        for text in ('定位当前位置', '重新定位当前位置', '机器狗，重新定位。', '请重新定位'):
            self.assertEqual(parse(text), {'action': 'relocalize'})
        for text in ('不要重新定位', '别定位当前位置', '定位当前位置然后去门口', '如果能定位当前位置', '已定位'):
            self.assertIsNone(parse(text))
        self.assertIn('定位 当前 位置', phrases())
        session = WakeSession()
        self.assertEqual(session.feed('定位当前位置')[0], 'needs_wake')
        event, token = session.feed('小爱同学')
        session.reply_finished(token)
        self.assertEqual(session.feed('定位当前位置'), ('command', {'action': 'relocalize'}))

    def test_success_requires_verified_result_and_exit_status(self):
        for code, data in [(1, {'success': True, 'verified': True}),
                           (0, {'success': True, 'published_initialpose': True}),
                           (0, {'candidate_valid': True, 'success': False})]:
            self.assertFalse(verified_result(code, json.dumps(data))[0])
        self.assertTrue(verified_result(0, json.dumps({'success': True, 'verified': True}))[0])
        self.assertFalse(verified_result(0, 'not json')[0])

    def worker(self, code=0, result=None):
        events, calls = [], []
        worker = VoiceRelocalizer(SimpleNamespace(posture_busy=False), lambda **e: events.append(e))
        def run(command, timeout, cancel):
            calls.append(command)
            if len(calls) == 1:
                return code, json.dumps(result or {}), ''
            return 0, '', ''
        worker._run_command = run
        worker.busy = True
        return worker, events, calls

    def test_success_and_failure_select_exact_cached_reply(self):
        for success in (False, True):
            worker, events, calls = self.worker(result={'success': success, 'verified': success})
            worker._execute(threading.Event())
            result = next(e for e in events if e['event'] == 'localization_result')
            self.assertEqual(result['reply'], '已定位' if success else '请重新定位')
            self.assertIn('localization_success.wav' if success else 'localization_failure.wav', calls[-1][-1])
            self.assertFalse(worker.busy)

    def test_cancel_never_announces_success_or_replays_job(self):
        worker, events, calls = self.worker(result={'success': True, 'verified': True})
        cancelled = threading.Event();cancelled.set()
        worker._execute(cancelled)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('localization_result', [e['event'] for e in events])
        self.assertIn('localization_cancelled', [e['event'] for e in events])

    def test_posture_in_progress_does_not_run_localization(self):
        worker, events, calls = self.worker()
        worker.nav.posture_busy = True
        worker._execute(threading.Event())
        self.assertEqual(len(calls), 1)
        self.assertIn('localization_failure.wav', calls[0][-1])

    def test_dispatch_cancels_stale_goal_and_blocks_new_motion(self):
        from voice_navigation import Navigator
        nav = Navigator.__new__(Navigator)
        nav.patrol = SimpleNamespace(active=False, cancel=lambda:None)
        calls = []
        nav.relocalizer = SimpleNamespace(busy=False, start=lambda: calls.append('start'),
                                          cancel=lambda: calls.append('cancel'))
        nav.battery_query = SimpleNamespace(busy=False)
        nav.stairs = SimpleNamespace(cancel=lambda _: calls.append('cancel_stairs'))
        nav.generation = 5
        nav.goal = SimpleNamespace(cancel_goal_async=lambda: calls.append('cancel_goal'))
        nav.dispatch({'action': 'relocalize'})
        self.assertEqual(calls, ['cancel_stairs', 'cancel_goal', 'start'])
        self.assertEqual(nav.generation, 6)
        nav.relocalizer.busy = True
        with patch('voice_navigation.report') as report:
            nav.dispatch({'action': 'stand'})
            self.assertEqual(report.call_args.kwargs['event'], 'rejected')
        self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
