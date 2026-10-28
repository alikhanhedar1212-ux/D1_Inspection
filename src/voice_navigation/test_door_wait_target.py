from project_config import config_path, map_path
import json, math, unittest
import yaml
from pathlib import Path
from door_wait_target import approach_target

class DoorWaitTargetTests(unittest.TestCase):
    def test_waypoint_one_used_for_navigation_and_handoff(self):
        root=Path(__file__).parent
        config=json.loads((config_path('stairs_task_config.json')).read_text())
        original=next(p for p in yaml.safe_load((map_path('waypoints.yaml')).read_text())['waypoints'] if p['id']==1)
        target=approach_target(config)
        for key in ('x','y','yaw'):self.assertEqual(target[key],original[key])
        self.assertEqual(config['waypoint_2d'],1)
        self.assertGreater(config['arrival_tolerance']['position_m'], 0)
        self.assertLessEqual(config['arrival_tolerance']['position_m'], .3)
        self.assertAlmostEqual(config['arrival_tolerance']['yaw_rad'],math.radians(15))

    def test_unconfirmed_or_nonfinite_target_rejected(self):
        for target in ({'confirmed':False,'x':0,'y':0,'yaw':0},
                       {'confirmed':True,'x':float('nan'),'y':0,'yaw':0},
                       {'confirmed':True,'x':0,'y':0,'yaw':float('inf')}):
            with self.subTest(target=target),self.assertRaises(ValueError):
                approach_target({'approach_target_2d':target})

    def test_explicit_waypoint_takes_priority_over_retired_custom_target(self):
        config={'approach_target_2d':{'confirmed':True,'x':1,'y':2,'yaw':.3},'waypoint_2d':1}
        points=yaml.safe_load((map_path('waypoints.yaml')).read_text())['waypoints']
        expected=next(p for p in points if p['id']==1)
        self.assertEqual(approach_target(config)['x'],expected['x'])
        result=approach_target(config);result['x']=99
        self.assertEqual(config['approach_target_2d']['x'],1)
