"""Exercise relocation and remote shell quoting without ROS or robot access."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deployment


class DeploymentTests(unittest.TestCase):
    def test_module_resources_are_in_their_owned_directories(self):
        resources = [deployment.config_path('config.example.json'),
                     deployment.config_path('motion.yaml'),
                     deployment.map_path('map.yaml'),
                     deployment.map_path('map.pgm'),
                     deployment.map_path('waypoints.yaml'),
                     deployment.map_path('patrol_config.json'),
                     deployment.ui_path('dashboard.html'),
                     deployment.ui_path('rviz/navigation_drive.rviz'),
                     deployment.behavior_path('navigate_arrival_v2.xml')]
        for path in resources:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

    def test_remote_home_and_special_characters_are_expanded_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)/'clone with spaces; dollar$'
            (clone/'src/voice_navigation').mkdir(parents=True)
            (clone/'src/voice_navigation/echo.py').write_text('import json,sys; print(json.dumps(sys.argv[1:]))')
            settings = dict(deployment.SETTINGS, aidlux_root='~/'+clone.name, aidlux_host='test-robot')
            text = "USB mic; $(touch SHOULD_NOT_EXIST) ' quoted"
            with patch.dict(deployment.SETTINGS, settings, clear=True):
                command = deployment.ssh_command('aidlux', [sys.executable, deployment.remote_file('aidlux', 'voice_navigation', 'echo.py'), text])
            self.assertIn('test-robot', command)
            result = subprocess.run(['bash', '-c', command[-1]], env=dict(os.environ, HOME=directory), cwd=directory, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), [text])
            self.assertFalse((Path(directory)/'SHOULD_NOT_EXIST').exists())

    def test_existing_device_layout_can_be_configured(self):
        with patch.dict(deployment.SETTINGS, {'firefly_drivers_dir': '~/existing control'}):
            self.assertEqual(deployment.remote_file('firefly','drivers','velocity_receiver.py'), '~/existing control/velocity_receiver.py')

    def test_motion_trees_follow_a_relocated_clone(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)/'different project name with spaces'
            (clone/'config').mkdir(parents=True)
            shutil.copy2(deployment.config_path('motion.yaml'),clone/'config/motion.yaml')
            with patch.object(deployment, 'ROOT', clone):
                params = deployment.motion_parameters()
                self.assertEqual(params['default_nav_to_pose_bt_xml'], str(clone/'src/navigation_localization/behavior_trees/navigate_arrival_v2.xml'))
                self.assertIn('FollowPath', deployment.motion_parameters('controller_server'))
                self.assertNotIn('bt_navigator', params)

    def test_runtime_shell_can_be_sourced_from_a_different_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)/'renamed clone with spaces'
            nav = clone/'src/navigation_localization'
            nav.mkdir(parents=True)
            (clone/'config').mkdir(parents=True)
            shutil.copy2(deployment.ROOT/'src/navigation_localization/runtime_env.sh',nav/'runtime_env.sh')
            shutil.copy2(deployment.config_path('cyclonedds.xml'),clone/'config/cyclonedds.xml')
            setup = Path(directory)/'ROS setup.bash'
            setup.write_text('export FAKE_ROS_READY=yes\n')
            command = f'source {shlex.quote(str(nav/"runtime_env.sh"))} && printf "%s\\n" "$FAKE_ROS_READY" "$CYCLONEDDS_URI"'
            result = subprocess.run(['bash','-c',command],env=dict(os.environ,D1_ROS_SETUP=str(setup)),cwd='/',capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout.splitlines(), ['yes', f'file://{clone}/config/cyclonedds.xml'])

    def test_config_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'settings.json'
            config.write_text(json.dumps({'aidlux_root':'~/my clone','aidlux_host':'user@robot'}))
            with patch.dict(os.environ, {'D1_CONFIG':str(config)}):
                settings = deployment.load_settings()
            self.assertEqual(settings['aidlux_host'],'user@robot')
            self.assertEqual(settings['aidlux_root'],'~/my clone')

    def test_voice_entrypoint_runs_from_a_renamed_clone_and_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory)/'renamed clone with spaces'
            clone.mkdir()
            shutil.copy2(deployment.ROOT/'deployment.py', clone/'deployment.py')
            shutil.copytree(deployment.ROOT/'src/voice_navigation', clone/'src/voice_navigation',
                            ignore=shutil.ignore_patterns('__pycache__', '.venv', 'models', 'audio'))
            result = subprocess.run(['bash', str(clone/'src/voice_navigation/run_local.sh'),
                                     '--text', '开始巡检'], cwd='/',
                                    env=dict(os.environ, D1_PYTHON=sys.executable),
                                    capture_output=True, text=True, check=True)
            event = json.loads(result.stdout)
            self.assertEqual(event['command'], {'action': 'patrol_start'})


if __name__ == '__main__':
    unittest.main()
