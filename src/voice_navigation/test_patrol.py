from project_config import map_path
import math
import json
import time
import threading
import unittest
import tempfile
import types
from patrol_routes import path_inside_route
from patrol_detection import load_detector, DetectorNotReady, CheckedDetector
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import cv2
import numpy as np
from commands import parse
from patrol_vision import Detector, StableDetection, ROOT
from patrol_runtime import PatrolRuntime, MissionError, Cancelled


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = Detector()

    def test_printed_references_at_camera_scale(self):
        for label in ('forward','left','right','uturn','extinguisher'):
            with self.subTest(label=label):
                f=cv2.resize(cv2.imread(str(ROOT/(label+'.png'))),(240,240))
                image=np.full((480,640,3),80,np.uint8);image[120:360,200:440]=f
                kind='extinguisher' if label=='extinguisher' else 'sign'
                self.assertEqual(self.detector.detect(image,kind)[0],label)

    def test_blanks_and_unrelated_signs_do_not_mean_extinguisher(self):
        for label in ('forward','left','right','uturn'):
            self.assertIsNone(self.detector.detect(cv2.imread(str(ROOT/(label+'.png'))),'extinguisher')[0])
        self.assertIsNone(self.detector.detect(np.zeros((480,640,3),np.uint8),'sign')[0])

    def test_three_consecutive_frames(self):
        s=StableDetection()
        self.assertIsNone(s.update('left'));self.assertIsNone(s.update('right'))
        self.assertIsNone(s.update('right'));self.assertEqual(s.update('right'),'right')
        self.assertIsNone(s.update(None))


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root_patch = patch('patrol_runtime.ROOT', Path(self.tmp.name))
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def mission(self, labels):
        p=PatrolRuntime.__new__(PatrolRuntime)
        p.config=json.loads((map_path('patrol_config.json')).read_text())
        p.config['mode']='inspection';p.config['order']=[2,1,3,4]
        p.config.pop('stop_overrides',None)
        p.cancelled=threading.Event();p.fault=None;p.active=True;p.goal=None
        p.events=[];p.report=lambda **d:p.events.append(d)
        p._check=lambda:None;p._stop_motion=lambda:None
        p.visited=[];p.spoken=[];p._navigate=lambda point:p.visited.append(point)
        p._visit=lambda point:p._navigate(point)
        p._say=lambda phrase,**kw:p.spoken.append(phrase)
        it=iter(labels);p._observe=lambda kind:next(it)
        return p

    def test_navigation_test_visits_four_points_then_returns_to_command_origin(self):
        p=self.mission([]);p.config.update(mode='navigation_test',order=[1,2,3,4])
        waited=[];p._dwell=lambda ident:waited.append(ident)
        p._observe=lambda kind:self.fail('simple route must not run detection')
        p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(p.visited,[p.config['points'][str(i)] for i in [1,2,3,4]]+[{'x':0,'y':0,'yaw':0}])
        self.assertEqual(waited,[1,2,3,4]);self.assertEqual(p.spoken,[])
        self.assertEqual(p.events[-1]['event'],'patrol_completed')

    def test_stop_during_wait_prevents_next_goal(self):
        p=self.mission([]);p.config.update(mode='navigation_test',order=[1,2,3,4])
        def stop(ident):
            p.cancelled.set()
            raise Cancelled()
        p._dwell=stop;p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(p.visited,[p.config['points']['1']])
        self.assertEqual(p.events[-1]['event'],'patrol_cancelled')

    def test_dwell_checks_health_and_waits_five_seconds(self):
        p=self.mission([]);clock=[0.];checks=[]
        p._check=lambda:checks.append(clock[0])
        p.cancelled=SimpleNamespace(wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
        with patch('patrol_runtime.time.monotonic',side_effect=lambda:clock[0]):p._dwell(1)
        self.assertGreaterEqual(clock[0],5.);self.assertGreater(len(checks),10)

    def test_frontdoor_aligns_fixed_map_heading_from_different_arrival_headings(self):
        import math
        for incoming in [0., math.pi, math.pi/2, -math.pi+.02]:
            p=self.mission([]);calls=[];headings=[incoming]
            p.nav=SimpleNamespace(acknowledge=lambda:None,save_destination=lambda unfinished:None)
            p._navigate=lambda point,position_only=False:calls.append(('navigate',position_only))
            p.pose=lambda:{'x':0.,'y':0.,'yaw':headings[-1]}
            def turn(angle,tolerance):
                calls.append(('turn',angle));headings.append(headings[-1]+angle)
            p._turn_around=turn
            p._frontdoor({'id':1,'x':0.,'y':0.,'yaw':math.pi/2})
            self.assertEqual(calls[0],('navigate',True))
            self.assertAlmostEqual(math.atan2(math.sin(headings[-1]-math.pi/2),math.cos(headings[-1]-math.pi/2)),0.)
            if incoming == math.pi/2:self.assertEqual(len(calls),1)
            else:self.assertLessEqual(abs(calls[-1][1]),math.pi)
            self.assertEqual(p.events[-1]['status'],4)

    def test_cancel_before_frontdoor_turn_prevents_rotation(self):
        p=self.mission([]);p.nav=SimpleNamespace(acknowledge=lambda:None)
        p._navigate=lambda *a,**kw:(_ for _ in ()).throw(Cancelled())
        p._turn_around=lambda angle:self.fail('cancelled mission must not turn')
        p._frontdoor({'id':1});self.assertFalse(p.active)

    def test_stale_action_handle_does_not_prevent_stop_service(self):
        p=self.mission([])
        p.goal=SimpleNamespace(cancel_goal_async=lambda:(_ for _ in ()).throw(RuntimeError('invalid action client')))
        called=[];response=object()
        p.nav=SimpleNamespace(stop_client=SimpleNamespace(service_is_ready=lambda:True,call_async=lambda req:(called.append(req) or response)))
        service=SimpleNamespace(Trigger=SimpleNamespace(Request=lambda:object()))
        with patch.dict('sys.modules',{'std_srvs.srv':service}):
            result=PatrolRuntime._stop_motion(p)
        self.assertIs(result,response);self.assertEqual(len(called),1);self.assertIsNone(p.goal)

    def test_shutdown_stop_service_error_does_not_crash_cleanup(self):
        p=self.mission([]);p.goal=None
        p.nav=SimpleNamespace(stop_client=SimpleNamespace(service_is_ready=lambda:(_ for _ in ()).throw(RuntimeError('context invalid'))))
        self.assertIsNone(PatrolRuntime._stop_motion(p))

    def test_staged_visit_stops_before_turn_and_checks_final_pose(self):
        p=self.mission([]);calls=[];target={'x':1.,'y':2.,'yaw':math.pi}
        poses=iter([dict(target,yaw=math.pi/2),target])
        p.pose=lambda:next(poses)
        p._navigate=lambda point,position_only=False:calls.append(('navigate',position_only))
        p._turn_around=lambda angle,tolerance:calls.append(('spin',angle,tolerance))
        p._park=lambda:calls.append(('park',))
        PatrolRuntime._visit(p,target)
        self.assertEqual(calls,[('navigate',True),('spin',math.pi/2,math.radians(15)),('park',)])

    def test_arrival_accepts_one_metre_and_fifteen_degrees(self):
        p=self.mission([]);point={'x':1.,'y':2.,'yaw':0.};calls=[]
        p._navigate=lambda *a,**kw:None
        p.pose=lambda:{'x':1.99,'y':2.,'yaw':math.radians(14.9)}
        p._turn_around=lambda *a,**kw:self.fail('already within user heading tolerance')
        p._park=lambda:calls.append('park')
        PatrolRuntime._visit(p,point);self.assertEqual(calls,['park'])

    def test_staged_visit_never_turns_after_cancel(self):
        p=self.mission([])
        p._navigate=lambda *a,**kw:(_ for _ in ()).throw(Cancelled())
        p._turn_around=lambda *a,**kw:self.fail('must not turn after cancellation')
        with self.assertRaises(Cancelled):PatrolRuntime._visit(p,{'x':1,'y':2,'yaw':0})

    def test_staged_visit_position_drift_fails_without_replanning_loop(self):
        p=self.mission([]);point={'x':1.,'y':2.,'yaw':0.}
        poses=iter([dict(point,yaw=-1.),dict(point,x=2.1)])
        p.pose=lambda:next(poses);p._navigate=lambda *a,**kw:None;p._turn_around=lambda *a,**kw:None
        p._park=lambda:self.fail('must not start dwell after drift')
        with self.assertRaises(MissionError):PatrolRuntime._visit(p,point)

    def test_second_stop_resolves_regular_washroom_without_changing_p2(self):
        import yaml
        import patrol_runtime
        p=self.mission([]);p.config.update(mode='navigation_test',order=[1,2,3,4],stop_overrides={'2':{'waypoint_id':2}})
        original=dict(p.config['points']['2']);p._dwell=lambda ident:None
        p._run({'x':0,'y':0,'yaw':0})
        washroom=next(w for w in yaml.safe_load((map_path('waypoints.yaml')).read_text())['waypoints'] if w['id']==2)
        self.assertTrue(all(p.visited[1][k]==value for k,value in washroom.items()))
        self.assertEqual(p.config['points']['2'],original)
        self.assertEqual(len(p.visited),5)

    def test_command_is_exact(self):
        self.assertEqual(parse('开始巡检'),{'action':'patrol_start'})
        self.assertIsNone(parse('不要开始巡检'))

    def test_left_and_right_visit_different_corridors(self):
        for sign in ('left','right','forward'):
            p=self.mission(['extinguisher',None,'extinguisher',sign]);home={'x':3.,'y':4.,'yaw':1.}
            with patch('patrol_vision.Detector'):
                p._run(home)
            self.assertEqual(p.visited[:4],[p.config['points'][str(i)] for i in (2,1,3,4)])
            self.assertEqual(p.visited[-1],home)
            self.assertEqual(p.spoken,['device_normal','device_missing','device_normal'])
            expected=len(p.config['return_routes'].get(sign,[]))
            self.assertEqual(len(p.visited),5+expected)
            self.assertEqual(p.events[-1]['event'],'patrol_completed')

    def test_unknown_sign_stops_without_return(self):
        p=self.mission(['extinguisher']*3+[None])
        with patch('patrol_vision.Detector'):p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(len(p.visited),4);self.assertEqual(p.spoken[-1],'sign_error')
        self.assertFalse(p.active)

    def test_unreachable_does_not_visit_next_point(self):
        p=self.mission([])
        def fail(point):raise MissionError('planning_error')
        p._navigate=fail
        with patch('patrol_vision.Detector'):p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(p.spoken,['planning_error'])
        self.assertFalse(p.active)

    def test_stop_never_resumes(self):
        p=self.mission([]);p.cancelled.set()
        p._check=lambda:(_ for _ in ()).throw(Cancelled())
        p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(p.visited,[]);self.assertEqual(p.spoken,[])

    def test_camera_fault_is_not_device_missing(self):
        p=self.mission([])
        def fail():raise MissionError('camera_error')
        p._check=fail
        p._run({'x':0,'y':0,'yaw':0})
        self.assertEqual(p.spoken,['camera_error'])

    def test_late_goal_is_cancelled(self):
        p=self.mission([]);p._check=lambda:(_ for _ in ()).throw(Cancelled())
        callbacks=[];future=SimpleNamespace(done=lambda:False,add_done_callback=callbacks.append)
        with self.assertRaises(Cancelled):p._wait(future,10,late_goal=True)
        cancelled=[];callbacks[0](SimpleNamespace(result=lambda:SimpleNamespace(accepted=True,cancel_goal_async=lambda:cancelled.append(True))))
        self.assertEqual(cancelled,[True])

    def test_precompleted_late_goal_is_still_cancelled(self):
        p=self.mission([]);p._check=lambda:(_ for _ in ()).throw(Cancelled())
        cancelled=[]
        result=SimpleNamespace(accepted=True,cancel_goal_async=lambda:cancelled.append(True))
        future=SimpleNamespace(done=lambda:True,result=lambda:result,add_done_callback=lambda cb:cb(future))
        with self.assertRaises(Cancelled):p._wait(future,10,late_goal=True)
        self.assertEqual(cancelled,[True])

    def test_branch_monitor_rejects_other_side_and_ignores_old_plan(self):
        p=self.mission([]);p.return_corridor=[p.config['points']['4']]+p.config['return_routes']['left']
        p.return_corridor_started=100
        q=p.config['return_routes']['right'][1]
        plan=SimpleNamespace(header=SimpleNamespace(frame_id='map',stamp=SimpleNamespace(sec=99,nanosec=0)),
            poses=[SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=q['x'],y=q['y'])))])
        p._plan(plan);self.assertFalse(p.cancelled.is_set())
        plan.header.stamp.sec=101;p._plan(plan)
        self.assertTrue(p.cancelled.is_set());self.assertEqual(p.fault,'planning_error')

    def test_camera_failure_during_observation_never_reports_missing(self):
        p=self.mission([]);p._check=lambda:(_ for _ in ()).throw(MissionError('camera_error'))
        p.lock=threading.Lock();p.frame_seq=1
        with self.assertRaisesRegex(MissionError,'camera_error'):PatrolRuntime._observe(p,'extinguisher')

    def test_rotation_is_pi_without_forward_leg(self):
        p=self.mission([]);p.nav=SimpleNamespace(node=None)
        positions=iter([{'x':0,'y':0,'yaw':0},{'x':0,'y':0,'yaw':3.141592653589793}])
        p.pose=lambda:next(positions);parked=[];p._park=lambda:parked.append(True)
        sent=[]
        def future(value):return SimpleNamespace(done=lambda:True,result=lambda:value)
        handle=SimpleNamespace(accepted=True,get_result_async=lambda:future(SimpleNamespace(status=4)))
        client=SimpleNamespace(wait_for_server=lambda **kw:True,send_goal_async=lambda g:(sent.append(g) or future(handle)),destroy=lambda:None)
        class Spin:
            class Goal:
                def __init__(self):self.time_allowance=SimpleNamespace(sec=0)
        modules={'nav2_msgs':types.ModuleType('nav2_msgs'),'nav2_msgs.action':SimpleNamespace(Spin=Spin),
                 'rclpy':types.ModuleType('rclpy'),'rclpy.action':SimpleNamespace(ActionClient=lambda *a:client)}
        with patch.dict('sys.modules',modules):p._turn_around()
        self.assertAlmostEqual(sent[0].target_yaw,3.141592653589793)
        self.assertEqual(p.visited,[]);self.assertEqual(parked,[True])

    def test_explicit_stop_clears_pending_fault_reply(self):
        p=self.mission([]);p.fault='camera_error';p.audio=None
        p.cancel();self.assertIsNone(p.fault)
        with self.assertRaises(Cancelled):PatrolRuntime._say(p,'camera_error',fault=True)

    def test_no_detection_waits_for_full_window(self):
        p=self.mission([]);p.config['observation_seconds']=.12;p.frame_seq=1;p.frame=None;p.lock=threading.Lock()
        start=time.monotonic();self.assertIsNone(PatrolRuntime._observe(p,'extinguisher'))
        self.assertGreaterEqual(time.monotonic()-start,.12)

    def test_left_and_right_corridors_are_distinct(self):
        p=self.mission([])
        left=[p.config['points']['4']]+p.config['return_routes']['left']
        right=[p.config['points']['4']]+p.config['return_routes']['right']
        self.assertFalse(path_inside_route([(right[2]['x'],right[2]['y'])],left))
        self.assertFalse(path_inside_route([(left[1]['x'],left[1]['y'])],right))


class AdapterTests(unittest.TestCase):
    def test_pending_model_refuses_to_start(self):
        with self.assertRaises(DetectorNotReady):load_detector({'backend':'external','module':None})

    def test_valid_external_classes_and_empty_inference(self):
        backend=SimpleNamespace(ready=lambda:True,detect=lambda frame,kind:(None,{'inference_ok':True}))
        module=SimpleNamespace(create_detector=lambda settings:backend)
        with patch.dict('sys.modules',{'test_trained_detector':module}):
            detector=load_detector({'backend':'external','module':'test_trained_detector'})
            self.assertEqual(detector.detect(None,'extinguisher'),(None,{'inference_ok':True}))

    def test_wrong_class_or_failed_inference_never_means_missing(self):
        wrong=CheckedDetector(SimpleNamespace(detect=lambda *a:('cat',{})))
        with self.assertRaises(RuntimeError):wrong.detect(None,'extinguisher')
        def fail(*args):raise RuntimeError('模型异常')
        with self.assertRaises(RuntimeError):CheckedDetector(SimpleNamespace(detect=fail)).detect(None,'extinguisher')


if __name__=='__main__':unittest.main()
