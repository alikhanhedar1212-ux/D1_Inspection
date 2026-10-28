import unittest
from types import SimpleNamespace
from stairs_task import StairsTask
from stairs_runtime import StairsRuntime
from door_wait_guard import DoorWaitGuard


class FirstDoorWaitTests(unittest.TestCase):
    def test_arrival_stops_and_requests_door_without_3d_or_crossing(self):
        m = StairsTask(first_door_wait_only=True)
        m.start()
        kinds = []
        while m.pending:
            e = m.pending
            kinds.append((e.kind, e.value))
            m.done(e.token)
        self.assertEqual(kinds, [('check', 'all_stages'), ('navigate_2d', 'door_wait'),
                                 ('stop', 'all_motion'), ('speak', 'request_open_door')])
        self.assertEqual(m.state, 'door_1_wait')
        self.assertTrue(m.active)
        self.assertFalse(m.awaiting_confirmation)
        for _ in range(10):
            self.assertEqual(m.tick(), [])
            self.assertEqual(m.confirm(), [])
        self.assertEqual(m.start(), [])
        with self.assertRaises(ValueError):
            m.start_passage(1, 'exit')
        m.cancel()
        m.done(m.pending.token)
        self.assertEqual(m.state, 'cancelled')

    def test_failed_standstill_never_announces(self):
        m = StairsTask(first_door_wait_only=True)
        m.start()
        m.done(m.pending.token)
        m.done(m.pending.token)
        self.assertEqual(m.state, 'stop_1')
        m.done(m.pending.token, False, '尚未停稳')
        self.assertEqual(m.pending.kind, 'stop')
        m.done(m.pending.token)
        self.assertEqual(m.state, 'failed')
        self.assertEqual(m.confirm(), [])

    def test_wait_mode_preflight_has_no_map_or_handoff_dependency(self):
        r = StairsRuntime.__new__(StairsRuntime)
        r.wait_only = True
        r.nav = SimpleNamespace(busy=False, posture_busy=False)
        calls = []
        r._check_2d = lambda: calls.append('2d')
        r._service = lambda *args: self.fail('must not call 3D service')
        r._preflight(None)
        self.assertEqual(calls, ['2d'])
        self.assertFalse(r.in_3d)

    def test_guard_requires_continuous_fresh_measured_standstill(self):
        g = DoorWaitGuard()
        for t in (10., 10.2, 10.4, 10.7):
            g.observe(t, 0., 0., 0., t, t)
        self.assertTrue(g.ready(10.7, 10.7))
        self.assertFalse(g.ready(11.5, 11.5))
        g.observe(12., 0., 0., 0., 12., 12.)
        self.assertFalse(g.ready(12., 12.))
        g.observe(12.2, .1, 0., 0., 12.2, 12.2)
        self.assertFalse(g.ready(12.2, 12.2))
        g.observe(12.4, float('nan'), 0., 0., 12.4, 12.4)
        self.assertFalse(g.ready(12.4, 12.4))


if __name__ == '__main__':
    unittest.main()
