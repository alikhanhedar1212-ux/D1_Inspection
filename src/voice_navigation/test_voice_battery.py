import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from battery_data import battery_reply, validate_sample
from commands import parse
from voice_battery import VoiceBatteryQuery
from wake import WakeSession


def sample(power=56):
    return {'source': 'battery_state', 'received_count': 2, 'sample_age_s': .02,
            'battery': {'power': power, 'volt': 45177, 'error': 527}}


class BatteryTests(unittest.TestCase):
    def test_intents_require_wake_and_reject_negation_or_mixed_actions(self):
        for text in ('还剩多少电', '还有多少电', '查询电量', '机器狗，电池电量。'):
            self.assertEqual(parse(text), {'action': 'battery_query'})
        for text in ('不要查询电量', '查询电量然后去门口', '当前电量百分之五十六'):
            self.assertIsNone(parse(text))
        session = WakeSession()
        self.assertEqual(session.feed('还剩多少电')[0], 'needs_wake')
        _, token = session.feed('小爱同学');session.reply_finished(token)
        self.assertEqual(session.feed('还剩多少电'), ('command', {'action': 'battery_query'}))

    def test_fresh_bounded_samples_and_zero_battery(self):
        self.assertEqual(validate_sample(sample(), 3), 56)
        zero = sample();del zero['battery']['power']
        self.assertEqual(validate_sample(zero, 3), 0)
        for value in (-1, 101, 56.2, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_sample(sample(value), 3)
        for key, value in [('sample_age_s', 4), ('received_count', 0), ('source', 'cached')]:
            bad = sample();bad[key] = value
            with self.assertRaises(ValueError):validate_sample(bad, 3)
        bad = sample();bad['battery'] = {}
        with self.assertRaises(ValueError):validate_sample(bad, 3)
        with self.assertRaises(ValueError):validate_sample(sample(), 12)

    def test_exact_spoken_numbers(self):
        for value, expected in [(0,'零'),(7,'七'),(10,'十'),(11,'十一'),(20,'二十'),(56,'五十六'),(100,'一百')]:
            self.assertEqual(battery_reply(value), '当前电量为百分之'+expected)

    def test_query_reads_new_data_then_uses_matching_reply_without_motion(self):
        for ok in (False, True):
            with tempfile.TemporaryDirectory() as directory, patch('voice_battery.ROOT', Path(directory)):
                calls, events = [], []
                worker = VoiceBatteryQuery(SimpleNamespace(), lambda **e: events.append(e))
                def run(command, timeout, cancelled):
                    calls.append(command)
                    if len(calls) == 1:
                        return (0, json.dumps(sample()), '') if ok else (1, '', 'disconnected')
                    return 0, '', ''
                worker._run_command = run
                worker._execute(threading.Event())
                result = next(e for e in events if e['event']=='battery_result')
                self.assertEqual(result['success'], ok)
                self.assertIn('D1_Inspection/src/drivers/read_battery_native', calls[0][-1])
                self.assertTrue(calls[1][-1].endswith(('56' if ok else 'unavailable') + "'"))
                self.assertFalse(any('cmd_vel' in arg or 'posture' in arg for cmd in calls for arg in cmd))
                self.assertFalse(worker.busy)

    def test_dispatch_does_not_cancel_active_navigation_for_query(self):
        from voice_navigation import Navigator
        nav = Navigator.__new__(Navigator)
        nav.patrol = SimpleNamespace(active=False, cancel=lambda:None)
        called = []
        nav.battery_query = SimpleNamespace(busy=False, start=lambda: called.append('query'))
        nav.relocalizer = SimpleNamespace(busy=False)
        nav.stairs = SimpleNamespace(speaking=False)
        nav.posture_busy = False
        nav.busy = True
        nav.dispatch({'action':'battery_query'})
        self.assertEqual(called, ['query'])
        self.assertTrue(nav.busy)


if __name__ == '__main__':
    unittest.main()
