import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from home_target import load_home, point_from_initial, record_verified_home


class HomeTargetTest(unittest.TestCase):
    def test_body_direction(self):
        point = point_from_initial({'state': 'initialized', 'hypotheses':
                                   [{'x': 1, 'y': 2, 'yaw': math.pi/2}]})
        self.assertAlmostEqual(point['yaw'], 0)
        self.assertEqual((point['x'], point['y']), (1, 2))

    def test_manual_pose_and_invalid_pose(self):
        point = point_from_initial({'state': 'manual', 'initial_pose':
                                   {'x': 3, 'y': 4, 'yaw': 0, 'body_frame': True}})
        self.assertEqual(point['yaw'], 0)
        for status in ({'state': 'waiting'}, {'state': 'existing'},
                       {'state': 'manual', 'initial_pose': {'x': math.nan, 'y': 0, 'yaw': 0}}):
            with self.assertRaises(ValueError):
                point_from_initial(status)

    def test_verified_localization_captures_origin_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=dict(success=True,verified=True,updated=110,amcl_pose=[1,2,math.pi/2])
            with patch('home_target.navigation_session',return_value=('session',100)):
                first=record_verified_home(root,result)
                self.assertEqual(first['yaw'],0.)
                result.update(updated=120,amcl_pose=[9,8,0])
                self.assertEqual(record_verified_home(root,result),first)
            with patch('home_target.navigation_session',return_value=('new',200)):
                with self.assertRaises(ValueError):record_verified_home(root,result)

    def test_journal_recovers_first_verified_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            rows=[dict(success=True,verified=True,updated=t,amcl_pose=[x,2,0]) for t,x in [(90,8),(120,9),(110,1)]]
            (root/'verified_localizations.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            with patch('home_target.navigation_session',return_value=('session',100)):
                self.assertEqual(load_home(root)['x'],1)

    def test_fixed_origin_and_new_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / 'auto_localization_status.json'
            def write(x, updated):
                status.write_text(json.dumps({'state': 'initialized', 'updated': updated,
                                             'hypotheses': [{'x': x, 'y': 2, 'yaw': 0}]}))
            write(1, 110)
            with patch('home_target.navigation_session', return_value=('first', 100)):
                self.assertEqual(load_home(root)['x'], 1)
                write(9, 120)
                self.assertEqual(load_home(root)['x'], 1)
            with patch('home_target.navigation_session', return_value=('second', 200)):
                with self.assertRaises(ValueError):
                    load_home(root)
                write(5, 210)
                self.assertEqual(load_home(root)['x'], 5)


if __name__ == '__main__':
    unittest.main()
