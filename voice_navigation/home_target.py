"""Return to the first localization in the current navigation session."""
import json
import math
import os
from pathlib import Path


def navigation_session(root):
    pid = int(json.loads((root / 'restored_processes.json').read_text())['navigation'])
    proc = Path('/proc') / str(pid)
    if str(root / 'restore.launch.py').encode() not in (proc / 'cmdline').read_bytes():
        raise ValueError('本轮导航进程不可用')
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    ticks = int(fields[19])
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    boot_time = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines()
                     if line.startswith('btime '))
    return f'{boot}:{pid}:{ticks}', boot_time + ticks / os.sysconf('SC_CLK_TCK')


def point_from_initial(status):
    if status.get('state') not in ('initialized', 'manual', 'existing'):
        raise ValueError('初始定位尚未完成')
    pose = status.get('initial_pose')
    if pose is None and status.get('state') == 'initialized':
        pose = dict(status['hypotheses'][0], body_frame=False)
    if not pose:
        raise ValueError('没有保存本轮初始位姿')
    x, y, yaw = (float(pose[k]) for k in ('x', 'y', 'yaw'))
    if not all(math.isfinite(v) for v in (x, y, yaw)):
        raise ValueError('初始位姿无效')
    # Existing nav_base -> nav_body is a pure -90 degree rotation.
    if not pose.get('body_frame', False):
        yaw -= math.pi / 2
    yaw = math.atan2(math.sin(yaw), math.cos(yaw))
    return {'id': 'home', 'name': '初始位置', 'x': x, 'y': y, 'yaw': yaw}


def record_verified_home(root, result):
    """Capture first verified localization; never replace an origin in this session."""
    import fcntl
    session, started = navigation_session(root)
    if not (result.get('success') is True and result.get('verified') is True):
        raise ValueError('定位尚未通过核验')
    updated = float(result['updated'])
    if updated < started:
        raise ValueError('定位记录属于上一次导航')
    pose = result['amcl_pose']
    point = point_from_initial({'state':'manual','initial_pose':
             dict(x=pose[0],y=pose[1],yaw=pose[2],body_frame=False)})
    automatic=root/'auto_localization_status.json'
    if automatic.exists():
        status=json.loads(automatic.read_text())
        if started <= status.get('updated',0) < updated:
            try:
                point=point_from_initial(status)
                updated=status['updated']
            except (ValueError,KeyError):
                pass
    saved = root/'home_target.json'
    with (root/'home_target.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if saved.exists():
            record = json.loads(saved.read_text())
            if record.get('session') == session:
                return record['point']
        record = dict(session=session,point=point,source='verified_localization',localization_updated=updated)
        temporary=saved.with_suffix('.tmp');temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2));temporary.replace(saved)
    return point


def load_home(root):
    session, started = navigation_session(root)
    saved = root / 'home_target.json'
    if saved.exists():
        record = json.loads(saved.read_text())
        if record.get('session') == session:
            return record['point']
    candidates=[]
    journal=root/'verified_localizations.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                result=json.loads(line)
                if result.get('success') is True and result.get('verified') is True and result.get('updated',0)>=started:
                    candidates.append(result)
            except ValueError:
                continue
    if candidates:
        return record_verified_home(root,min(candidates,key=lambda result:result['updated']))
    status = json.loads((root / 'auto_localization_status.json').read_text())
    if status.get('updated', 0) < started:
        raise ValueError('初始定位记录属于上一次导航，等待本轮定位')
    point = point_from_initial(status)
    record = {'session': session, 'point': point, 'source': status['state'],
              'localization_updated': status['updated']}
    temporary = saved.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    temporary.replace(saved)
    return point
