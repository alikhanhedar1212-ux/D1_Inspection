import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from commands import parse
from stairs_task import StairsTask
from stairs_runtime import StairsRuntime


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.time = 0.
        self.m = StairsTask(clock=lambda: self.time)

    def ack(self):
        self.assertIsNotNone(self.m.pending)
        return self.m.done(self.m.pending.token)

    def reach_first_door(self):
        self.m.start()
        for _ in range(4):
            self.ack()
        self.assertEqual(self.m.state, 'door_1_request')

    def answer_question(self):
        self.ack()  # request playback finishes
        self.time += 5
        self.assertEqual(self.m.tick()[0].value, 'confirm_door_open')
        self.assertFalse(self.m.awaiting_confirmation)
        self.ack()  # question playback finishes
        self.assertTrue(self.m.awaiting_confirmation)

    def test_check_before_any_motion(self):
        effects = self.m.start()
        self.assertEqual([(x.kind, x.value) for x in effects], [('check', 'all_stages')])
        effects = self.m.done(effects[0].token, False, '三维定位未接入')
        self.assertEqual(effects[0].kind, 'stop')
        self.ack()
        self.assertEqual(self.m.state, 'failed')
        self.assertIsNone(self.m.pending)

    def test_wait_five_seconds_after_request_finished(self):
        self.reach_first_door()
        self.time = 100
        self.assertEqual(self.m.tick(), [])
        self.ack()
        self.time = 104.999
        self.assertEqual(self.m.tick(), [])
        self.time = 105
        self.assertEqual(self.m.tick()[0].kind, 'speak')
        self.assertEqual(self.m.confirm(), [])  # cannot confirm during question
        self.ack()
        self.assertEqual(self.m.confirm()[0].value, 'door_2_wait')

    def test_early_confirm_not_buffered(self):
        self.reach_first_door()
        self.assertEqual(self.m.confirm(), [])
        self.answer_question()
        self.assertEqual(self.m.state, 'door_1_confirm')
        self.assertIsNone(self.m.pending)

    def test_two_independent_doors_and_stop_on_platform(self):
        self.reach_first_door()
        self.answer_question()
        self.assertEqual(self.m.confirm()[0].value, 'door_2_wait')
        self.assertEqual(self.m.confirm(), [])
        self.ack()  # arrive at door 2 wait point
        self.ack()  # stop before requesting door 2
        self.assertEqual(self.m.state, 'door_2_request')
        self.answer_question()
        self.assertEqual(self.m.confirm()[0].value, 'stairs_platform_center')
        self.assertEqual(self.m.confirm(), [])
        self.assertEqual(self.ack()[0].kind, 'stop')
        self.ack()
        self.assertEqual(self.m.state, 'complete')
        self.assertFalse(self.m.active)
        self.assertIsNone(self.m.pending)

    def test_stop_invalidates_late_arrival_and_timer(self):
        old = self.m.start()[0]
        stop = self.m.cancel()[0]
        self.assertEqual(self.m.done(old.token), [])
        self.assertEqual(self.m.pending, stop)
        self.ack()
        self.time += 999
        self.assertEqual(self.m.tick(), [])
        self.assertEqual(self.m.confirm(), [])

    def test_stop_during_gate_delay(self):
        self.reach_first_door()
        self.ack()
        self.m.cancel()
        self.ack()
        self.time += 10
        self.assertEqual(self.m.tick(), [])
        self.assertEqual(self.m.state, 'cancelled')

    def test_failed_prompt_never_unlocks(self):
        self.reach_first_door()
        self.m.done(self.m.pending.token, False, 'speaker disconnected')
        self.assertEqual(self.m.confirm(), [])
        self.ack()
        self.assertEqual(self.m.state, 'failed')

    def test_failed_stop_does_not_retry_forever(self):
        self.m.start()
        self.m.cancel()
        self.assertEqual(self.m.done(self.m.pending.token, False, 'stop failed'), [])
        self.assertIsNone(self.m.pending)
        self.assertEqual(self.m.state, 'failed')

    def test_restart_does_not_resume(self):
        self.reach_first_door()
        fresh = StairsTask()
        self.assertEqual(fresh.state, 'idle')
        self.assertEqual(fresh.confirm(), [])

    def test_duplicate_start_does_not_replace_active_task(self):
        effect = self.m.start()[0]
        self.assertEqual(self.m.start(), [])
        self.assertEqual(self.m.pending, effect)

    def test_cancel_then_new_task_rejects_old_confirmation_and_callbacks(self):
        self.reach_first_door()
        old = self.m.pending
        self.m.cancel()
        self.ack()
        self.m.start()
        self.assertEqual(self.m.done(old.token), [])
        self.assertEqual(self.m.confirm(), [])

    def test_production_preflight_refuses_uncommissioned_route(self):
        runtime = StairsRuntime.__new__(StairsRuntime)
        runtime.handoff_only = False
        runtime.nav = SimpleNamespace(busy=False, posture_busy=False)
        client = SimpleNamespace(service_is_ready=lambda: False, server_is_ready=lambda: False)
        runtime.check_client = runtime.switch_client = runtime.stop_3d_client = runtime.confirm_client = runtime.client_3d = client
        with self.assertRaisesRegex(RuntimeError, '二维/三维坐标未标定'):
            runtime._preflight(None)

    def test_parse_exact_confirmation_and_reject_negation(self):
        self.assertEqual(parse('下楼'), {'action': 'stairs_approach'})
        self.assertEqual(parse('确认'), {'action': 'confirm_door'})
        for text in ('不要下楼', '不确认', '确认是否已开门', '确认后再走', '确认确认', '门还没开', '下楼然后回来'):
            self.assertIsNone(parse(text), text)

    def test_four_passages_each_require_a_new_confirmation(self):
        for door in (1,2):
            for direction in ('enter','exit'):
                with self.subTest(door=door,direction=direction):
                    m=StairsTask(clock=lambda:self.time)
                    self.assertEqual(m.confirm(), [])
                    m.start_passage(door,direction)
                    m.done(m.pending.token) # preflight -> approach
                    self.assertEqual(m.state,'passage_approach')
                    m.done(m.pending.token) # approach -> stop
                    self.assertEqual(m.pending.kind,'stop')
                    m.done(m.pending.token) # stopped -> request
                    self.assertEqual(m.confirm(), [])
                    m.done(m.pending.token) # request -> delay
                    self.time+=5;m.tick()
                    self.assertEqual(m.confirm(), [])
                    m.done(m.pending.token) # question completed
                    self.assertTrue(m.awaiting_confirmation)
                    effect=m.confirm()[0]
                    side='inside' if direction=='enter' else 'outside'
                    self.assertEqual(effect.value,f'door_{door}_{side}_wait')
                    self.assertEqual(m.confirm(), [])
                    m.done(effect.token);m.done(m.pending.token)
                    self.assertEqual(m.state,'complete')
                    self.assertEqual(m.confirm(), [])
                    m.start_passage(door,direction)
                    self.assertEqual(m.confirm(), [])

    def test_passage_commands_are_explicit(self):
        for door in (1,2):
            for word,direction in [('进','enter'),('出','exit')]:
                self.assertEqual(parse(f'{word}{door}号门'),{'action':'door_passage','door':door,'direction':direction})
        for phrase in ('不要进1号门','进1号门然后出2号门','不确认'):
            self.assertIsNone(parse(phrase))

    @unittest.skipUnless((Path(__file__).parent.parent/'stairs_mapping/maps/dimensioned_reference_preview/geometry.json').is_file(), 'Optional stairs geometry is not included in the patrol repository')
    def test_fixed_point_stays_on_platform_facing_stair(self):
        c=json.loads((Path(__file__).parent/'stairs_task_config.json').read_text())
        p=c['targets']['stairs_platform_center']
        self.assertEqual(p['z'],0.)
        geometry=json.loads((Path(__file__).parent.parent/'stairs_mapping/maps/dimensioned_reference_preview/geometry.json').read_text())
        ready=geometry.get('stairs_ready')
        import math
        if ready:
            self.assertAlmostEqual(p['yaw'],ready['yaw'])
            self.assertEqual([p['x'],p['y'],p['z']],ready['position'])
            self.assertFalse(p['confirmed'])
        else:
            self.assertAlmostEqual(p['yaw'],math.pi)
            self.assertAlmostEqual(p['x'],c['targets']['door_2_wait']['x'])
        self.assertFalse(c['execution_enabled'])


if __name__ == '__main__':
    unittest.main()


class HandoffTests(unittest.TestCase):
    def test_confirmation_keeps_robot_stopped(self):
        now=[0.]
        m=StairsTask(clock=lambda:now[0],stop_at_first_confirmation=True)
        effects=m.start()
        kinds=[]
        while m.pending:
            effect=m.pending;kinds.append(effect.kind)
            m.done(effect.token)
        self.assertEqual(m.state,'door_1_delay')
        self.assertEqual(kinds,['check','navigate_2d','stop','switch','speak'])
        self.assertEqual(m.confirm(),[])
        now[0]=4.99;self.assertEqual(m.tick(),[])
        now[0]=5.;question=m.tick()[0]
        self.assertEqual(m.confirm(),[])
        m.done(question.token)
        stop=m.confirm()[0]
        self.assertEqual(stop.kind,'stop')
        m.done(stop.token)
        self.assertEqual(m.state,'complete')
        self.assertEqual(m.confirm(),[])

    def test_handoff_failure_never_speaks(self):
        m=StairsTask(stop_at_first_confirmation=True);m.start()
        for _ in range(3):m.done(m.pending.token)
        self.assertEqual(m.pending.kind,'switch')
        effect=m.done(m.pending.token,False,'window missing')[0]
        self.assertEqual(effect.kind,'stop')
        m.done(effect.token)
        self.assertEqual(m.state,'failed')

class HandoffAnnouncementTests(unittest.TestCase):
    def test_announce_only_after_prepare_success(self):
        runtime=StairsRuntime.__new__(StairsRuntime)
        runtime.handoff_only=True
        runtime.handoff_prepare=object()
        runtime.in_3d=False
        calls=[]
        runtime._service=lambda *args:calls.append('prepared')
        runtime._play_prompt=lambda effect,key:calls.append(key)
        runtime._perform(SimpleNamespace(kind='switch'))
        self.assertEqual(calls,['prepared','map_3d_ready'])
        self.assertTrue(runtime.in_3d)

    def test_no_success_announcement_on_failed_switch(self):
        runtime=StairsRuntime.__new__(StairsRuntime)
        runtime.handoff_only=True
        runtime.handoff_prepare=object()
        runtime.in_3d=False
        calls=[]
        def fail(*args):raise RuntimeError('map not ready')
        runtime._service=fail
        runtime._play_prompt=lambda *args:calls.append('spoken')
        with self.assertRaises(RuntimeError):runtime._perform(SimpleNamespace(kind='switch'))
        self.assertEqual(calls,[])
        self.assertFalse(runtime.in_3d)
