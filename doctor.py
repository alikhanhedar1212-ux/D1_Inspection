"""Read-only checks for dependencies and deployment resources; never moves a robot."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys

from deployment import ROOT, local_path, setting


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--robot', action='store_true', help='Also check local ROS and voice assets')
    args = parser.parse_args()
    checks = [('dashboard', (ROOT/'voice_navigation/dashboard.html').is_file())]
    if args.robot:
        checks += [(module, importlib.util.find_spec(module) is not None)
                   for module in ('yaml', 'numpy', 'cv2', 'vosk', 'rclpy', 'nav2_msgs')]
        checks += [(name, shutil.which(name) is not None) for name in ('ssh', 'pactl', 'parec', 'paplay', 'ros2', 'rviz2')]
        checks += [('ROS setup', local_path(setting('ros_setup')).is_file()),
                   ('Vosk model', (ROOT/'voice_navigation/models/vosk-model-small-cn-0.22/am/final.mdl').is_file()),
                   ('behavior tree plugin', (ROOT/'navigation_localization/terminal_replan/build/libterminal_replan_bt_node.so').is_file())]
        for name in ('wake_reply', 'okay', 'device_normal', 'device_missing', 'camera_error', 'planning_error', 'sign_error'):
            checks.append((f'audio/{name}.wav', (ROOT/f'voice_navigation/audio/{name}.wav').is_file()))
        checks.append(('Newmine noise profile', (ROOT/'voice_navigation/newmine_noise_profile.npz').is_file()))
    for name, success in checks:
        print(f'{"OK" if success else "MISSING"}: {name}')
    if args.robot:
        print('Remote drivers, DDS plugins, SSH access and site calibration must also be commissioned; no robot commands were sent.')
    return 0 if all(success for _, success in checks) else 1


if __name__ == '__main__':
    sys.exit(main())
