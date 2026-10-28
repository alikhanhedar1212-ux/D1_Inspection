"""Remove measured chassis reflections from the virtual obstacle scan only.

Coordinates are in the gravity-levelled, yaw-aligned nav_scan frame. The
captures show reflections in two narrow longitudinal patches, rather than
a full circle around the lidar. Bounds include a small allowance for sway.
"""
import numpy as np


def chassis_returns(points):
    return ((np.abs(points[:, 0]) <= .10)
            & (np.abs(points[:, 1]) >= .45)
            & (np.abs(points[:, 1]) <= .70)
            & (points[:, 2] >= -.35)
            & (points[:, 2] <= .20))
