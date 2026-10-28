"""Portable project paths and explicitly configured robot connections."""
import json
import os
from pathlib import Path, PurePosixPath
import shlex

ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    'ros_setup': '/opt/ros/humble/setup.bash',
    'aidlux_host': 'aidlux',
    'firefly_host': 'firefly',
    'aidlux_root': '~/D1_Inspection',
    'firefly_root': '~/D1_Inspection',
    'aidlux_workspace_setup': '',
    'firefly_workspace_setup': '/opt/robot/robot-forward/install/setup.bash',
    'aidlux_domain': 0,
    'firefly_domain': 24,
    'microphone': 'alsa_input.usb-Newmine_Newmine_20180508-00.analog-stereo',
    'speaker': 'alsa_output.usb-Generic_USB2.0_Device_20170726905923-01.analog-stereo',
    'camera_device': '/dev/video2',
    'mapping_config': 'config/lio.template.yaml',
}


def load_settings():
    path = Path(os.environ.get('D1_CONFIG', ROOT / 'config/config.local.json')).expanduser()
    settings = dict(DEFAULTS)
    if path.is_file():
        overrides = json.loads(path.read_text())
        if not isinstance(overrides, dict):
            raise ValueError(f'Expected a JSON object in {path}')
        settings.update(overrides)
    return settings


SETTINGS = load_settings()


def setting(name):
    return SETTINGS[name]


def config_path(name):
    return ROOT / 'config' / name


def map_path(name):
    return ROOT / 'maps' / name


def ui_path(name):
    return ROOT / 'UI' / name


def behavior_path(name):
    return ROOT / 'src' / 'navigation_localization' / 'behavior_trees' / name


def local_path(value):
    path = Path(os.path.expandvars(str(value))).expanduser()
    return path if path.is_absolute() else ROOT / path


def remote_file(role, area, filename=''):
    # Optional per-area overrides support existing installations as well as clones.
    directory = SETTINGS.get(f'{role}_{area}_dir')
    if not directory:
        directory = str(PurePosixPath(setting(f'{role}_root')) / 'src' / area)
    return str(PurePosixPath(directory) / filename)


def shell_arg(value):
    """Quote a remote argument, expanding ~ on the remote host, never locally."""
    value = str(value)
    if value.startswith('~/'):
        return '"$HOME"/' + shlex.quote(value[2:])
    if value == '~':
        return '"$HOME"'
    return shlex.quote(value)


def ros_prefix(role):
    setup = SETTINGS.get(f'{role}_ros_setup', setting('ros_setup'))
    workspace = setting(f'{role}_workspace_setup')
    middleware = 'rmw_zenoh_cpp' if role == 'firefly' else 'rmw_fastrtps_cpp'
    parts = [f'source {shell_arg(setup)}']
    if workspace:
        parts.append(f'source {shell_arg(workspace)}')
    parts.append(f'export ROS_DOMAIN_ID={int(setting(role+"_domain"))} '
                 f'RMW_IMPLEMENTATION={middleware} OPENBLAS_NUM_THREADS=1')
    return ' && '.join(parts) + ' && '


def ssh_command(role, args, *, ros=False, timeout=8):
    command = (ros_prefix(role) if ros else '') + 'exec ' + ' '.join(map(shell_arg, args))
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', f'ConnectTimeout={timeout}',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
            setting(role + '_host'), 'bash -c ' + shlex.quote(command)]


def motion_parameters(node='bt_navigator'):
    """Resolve Nav2 behavior trees against this clone, regardless of cwd."""
    import yaml
    config = yaml.safe_load(config_path('motion.yaml').read_text())
    parameters = config['bt_navigator']['ros__parameters']
    for name in ('default_nav_to_pose_bt_xml', 'default_nav_through_poses_bt_xml'):
        path = Path(parameters[name])
        parameters[name] = str(path if path.is_absolute() else behavior_path(path))
    return config[node]['ros__parameters']


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Print a deployment setting')
    parser.add_argument('--get', required=True, choices=sorted(SETTINGS))
    print(setting(parser.parse_args().get))
