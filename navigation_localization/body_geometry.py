"""Planar lidar/IMU origin to body-center geometry; no ROS or motion commands."""
import json
import math
from pathlib import Path

import numpy as np


def body_pose(x, y, yaw, offset_x=0., offset_y=0., yaw_offset=-math.pi/2):
    """Offsets are nav_base -> nav_body, expressed in nav_base coordinates."""
    c, s = math.cos(yaw), math.sin(yaw)
    return (x+c*offset_x-s*offset_y, y+s*offset_x+c*offset_y,
            math.atan2(math.sin(yaw+yaw_offset), math.cos(yaw+yaw_offset)))


def body_pose_covariance(covariance, yaw, offset_x, offset_y):
    """Propagate yaw uncertainty into body-center translation uncertainty."""
    covariance = np.asarray(covariance, dtype=float).reshape(6, 6)
    jacobian = np.eye(6)
    jacobian[0, 5] = -math.sin(yaw)*offset_x-math.cos(yaw)*offset_y
    jacobian[1, 5] = math.cos(yaw)*offset_x-math.sin(yaw)*offset_y
    return (jacobian@covariance@jacobian.T).ravel().tolist()


def load_offset(path):
    path = Path(path)
    if not path.exists():
        return 0., 0.
    config = json.loads(path.read_text())
    if config.get('calibrated') is not True:
        return 0., 0.
    x, y = float(config['offset_x_m']), float(config['offset_y_m'])
    if not all(math.isfinite(v) for v in (x, y)) or math.hypot(x, y) > .6:
        raise ValueError('机身中心标定偏移无效')
    return x, y


def fit_rotation_center(samples):
    """Fit p_lio = fixed_center - R(yaw)*offset for confirmed in-place rotation.

    Cannot distinguish physical translation or LIO drift from a mounting offset
    without a stationary-body observation; caller must obtain that confirmation.
    """
    a = np.asarray(samples, dtype=float)
    if a.ndim != 2 or a.shape[1] != 4 or len(a) < 30 or not np.isfinite(a).all():
        raise ValueError('需要至少30条有效时间/x/y/yaw样本')
    if np.any(np.diff(a[:, 0]) <= 0) or a[-1, 0]-a[0, 0] < 2:
        raise ValueError('采样时间无效或不足2秒')
    angle = np.unwrap(a[:, 3])
    if np.ptp(angle) < math.radians(60):
        raise ValueError('旋转角度不足60度，不能估计中心偏移')
    c, s = np.cos(a[:, 3]), np.sin(a[:, 3])
    design = np.zeros((len(a)*2, 4))
    design[::2] = np.column_stack((np.ones(len(a)), np.zeros(len(a)), -c, s))
    design[1::2] = np.column_stack((np.zeros(len(a)), np.ones(len(a)), -s, -c))
    if np.linalg.cond(design) > 100:
        raise ValueError('旋转采样分布不足以稳定拟合')
    solution, _, _, _ = np.linalg.lstsq(design, a[:, 1:3].ravel(), rcond=None)
    center, offset = solution[:2], solution[2:]
    corrected = np.array([body_pose(x, y, yaw, *offset)[:2] for _, x, y, yaw in a])
    residual = np.linalg.norm(corrected-center, axis=1)
    if np.linalg.norm(offset) > .6 or np.sqrt(np.mean(residual**2)) > .04 or residual.max() > .10:
        raise ValueError('轨迹不符合固定中心旋转：可能有实际平移、定位漂移或采样异常')
    split = len(a)//2
    estimates = []
    for part in (slice(0, split), slice(split, len(a))):
        ids = np.arange(len(a))[part]
        rows = np.column_stack((ids*2, ids*2+1)).ravel()
        estimates.append(np.linalg.lstsq(design[rows], a[part, 1:3].ravel(), rcond=None)[0][2:])
    if np.linalg.norm(estimates[0]-estimates[1]) > .05:
        raise ValueError('前后半段估计偏移不一致，拒绝标定')
    return dict(offset_x_m=float(offset[0]), offset_y_m=float(offset[1]),
                rms_residual_m=float(np.sqrt(np.mean(residual**2))),
                max_residual_m=float(residual.max()),
                rotation_degrees=float(math.degrees(np.ptp(angle))), samples=len(a))
