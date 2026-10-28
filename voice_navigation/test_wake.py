import unittest
from wake import WakeSession


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.s = WakeSession(clock=lambda: self.now, window=10)

    def awaken(self):
        event, token = self.s.feed('小爱同学')
        self.assertEqual(event, 'wake')
        self.assertTrue(self.s.reply_finished(token))

    def test_no_goal_before_wake(self):
        self.assertEqual(self.s.feed('去门口')[0], 'needs_wake')

    def test_only_new_wake_phrase_is_enabled(self):
        for phrase in ('太乙真人', '小爱小爱', '小爱', '不要小爱同学', '小爱同学然后去门口'):
            self.assertNotEqual(WakeSession().feed(phrase)[0], 'wake')
        for phrase in ('小爱同学', '小爱 同学', '小 爱 同 学'):
            self.assertEqual(WakeSession().feed(phrase)[0], 'wake')

    def test_window_starts_after_reply(self):
        event, token = self.s.feed('小 爱 同 学')
        self.now = 20
        self.assertEqual(self.s.feed('去门口')[0], 'ignored')
        self.s.reply_finished(token)
        self.now = 29.99
        self.assertEqual(self.s.feed('去门口'), ('command', {'action': 'go', 'id': 1}))
        self.assertEqual(self.s.phase, 'awake')
        self.now = 39.99
        self.assertEqual(self.s.feed('去门口')[0], 'needs_wake')

    def test_timeout_boundary_and_noise(self):
        self.awaken()
        self.now = 9
        self.s.feed('今天是星期一')
        self.now = 10
        self.assertTrue(self.s.expire())
        self.assertEqual(self.s.feed('去一号位置')[0], 'needs_wake')

    def test_stop_without_wake(self):
        self.assertEqual(self.s.feed('停止'), ('command', {'action': 'stop'}))

    def test_late_reply_after_disconnect_does_not_awaken(self):
        _, token = self.s.feed('小爱同学')
        self.s.reset()
        self.assertFalse(self.s.reply_finished(token))
        self.assertEqual(self.s.phase, 'sleeping')

    def test_failed_reply_and_low_confidence(self):
        event, token = self.s.feed('小爱同学', .2)
        self.assertEqual(event, 'wake')
        self.s.reply_finished(token, False)
        self.assertEqual(self.s.feed('去门口')[0], 'needs_wake')

    def test_each_command_executes_immediately_and_refreshes_timeout(self):
        self.awaken()
        self.now = 8
        self.assertEqual(self.s.feed('去一号位置'), ('command', {'action': 'go', 'id': 1}))
        self.assertEqual(self.s.deadline, 18)
        self.now = 17
        self.assertEqual(self.s.feed('去二号位置'), ('command', {'action': 'go', 'id': 2}))
        self.assertEqual(self.s.deadline, 27)
        self.now = 26
        self.assertFalse(self.s.expire())
        self.now = 27
        self.assertTrue(self.s.expire())

    def test_stop_refreshes_awake_window_and_noise_does_not(self):
        self.awaken()
        self.now = 9
        self.assertEqual(self.s.feed('停止')[0], 'command')
        self.assertEqual(self.s.phase, 'awake')
        self.assertEqual(self.s.deadline, 19)
        self.now = 18
        self.s.feed('去门口', .1)
        self.s.feed('今天天气不错')
        self.assertEqual(self.s.deadline, 28)

    def test_low_confidence_keywords_require_wake(self):
        self.assertEqual(self.s.feed('1号', 0)[0], 'needs_wake')
        self.awaken()
        self.assertEqual(self.s.feed('正门', 0), ('command', {'action': 'go', 'id': 1}))
        self.assertEqual(self.s.feed('停止', 0), ('command', {'action': 'stop'}))


if __name__ == '__main__':
    unittest.main()


class ThirtySecondWindowTests(unittest.TestCase):
    def test_default_window_and_command_refresh(self):
        now = [0.]
        session = WakeSession(clock=lambda: now[0])
        _, token = session.feed('小爱同学')
        session.reply_finished(token)
        self.assertEqual(session.deadline, 30)
        now[0] = 29
        self.assertEqual(session.feed('一号')[0], 'command')
        self.assertEqual(session.deadline, 59)
        now[0] = 58
        self.assertFalse(session.expire())
        now[0] = 59
        self.assertTrue(session.expire())
        self.assertEqual(session.feed('正门')[0], 'needs_wake')
