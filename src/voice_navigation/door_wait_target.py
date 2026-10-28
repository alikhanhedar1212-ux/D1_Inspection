"""Shared target resolution for downstairs navigation and door handoff."""
from project_config import map_path
import math
from pathlib import Path
import yaml

def approach_target(config):
    waypoint_id = config.get('waypoint_2d')
    if waypoint_id is not None:
        points = yaml.safe_load((map_path('waypoints.yaml')).read_text())['waypoints']
        target = dict(next(p for p in points if p['id'] == waypoint_id))
    else:
        target = dict(config['approach_target_2d'])
    if target.get('confirmed') is not True:
        raise ValueError('门前目标点尚未确认')
    for key in ('x', 'y', 'yaw'):
        target[key] = float(target[key])
        if not math.isfinite(target[key]):
            raise ValueError('门前目标点坐标或朝向无效')
    return target
