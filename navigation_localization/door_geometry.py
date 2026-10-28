"""Read-only doorway hypotheses from vertical wall returns; never motion approval."""
import numpy as np


def doorway_candidates(points, seed=17):
    """Body frame XYZ in metres. Return geometric hypotheses, not semantic detections."""
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError('expected Nx3 body-frame points')
    p = p[np.isfinite(p).all(axis=1)]
    p = p[(p[:, 0] > .3) & (p[:, 0] < 2.5) & (abs(p[:, 1]) < 3)
          & (p[:, 2] > .05) & (p[:, 2] < .85)]
    if len(p) < 80:
        return []
    _, ids = np.unique(np.floor(p / .025).astype(int), axis=0, return_index=True)
    p = p[ids]
    rng = np.random.default_rng(seed)
    best = None
    # A near-frontal wall is represented as forward = intercept + slope * left.
    for _ in range(160):
        u, v = p[rng.choice(len(p), 2, replace=False)]
        if abs(u[1] - v[1]) < 1.:
            continue
        slope = (u[0] - v[0]) / (u[1] - v[1])
        if abs(slope) > np.tan(np.deg2rad(25)):
            continue
        intercept = u[0] - slope * u[1]
        d = abs(p[:, 0] - intercept - slope * p[:, 1]) / np.sqrt(1 + slope * slope)
        mask = d < .035
        if best is None or mask.sum() > best[0]:
            best = (int(mask.sum()), mask)
    if best is None or best[0] < 60:
        return []
    wall = p[best[1]]
    slope, intercept = np.polyfit(wall[:, 1], wall[:, 0], 1)
    # Require vertical support per strip. Isolated scan rows cannot define a jamb.
    step = .04
    bins = np.arange(-3., 3. + step, step)
    ids = np.clip(np.searchsorted(bins, wall[:, 1], side='right') - 1, 0, len(bins) - 2)
    occupied = np.zeros(len(bins) - 1, dtype=bool)
    for i in np.unique(ids):
        z = wall[ids == i, 2]
        occupied[i] = len(z) >= 4 and np.ptp(z) >= .25
    # Close a single missing strip; sparse sampling is not a door opening.
    for i in range(1, len(occupied) - 1):
        if occupied[i-1] and occupied[i+1]:
            occupied[i] = True
    occupied_ids = np.flatnonzero(occupied)
    if not len(occupied_ids):
        return []
    results = []
    for lo, hi in zip(occupied_ids[:-1], occupied_ids[1:]):
        width = (hi - lo - 1) * step * np.sqrt(1 + slope * slope)
        if not .75 <= width <= 1.8:
            continue
        if occupied[max(0, lo-8):lo+1].sum() < 6 or occupied[hi:hi+9].sum() < 6:
            continue
        right = (bins[lo+1] + bins[hi]) / 2 - (hi-lo-1)*step/2
        left = bins[hi]
        mid = (right + left) / 2
        center = [float(intercept + slope * mid), float(mid)]
        results.append({'state': 'candidate_only', 'motion_authorized': False,
                        'center_body_xy_m': center, 'width_m': float(width),
                        'right_body_xy_m': [float(intercept+slope*right), float(right)],
                        'left_body_xy_m': [float(intercept+slope*left), float(left)],
                        'normal_yaw_rad': float(-np.arctan(slope)),
                        'wall_support_voxels': len(wall),
                        'warning': 'Wall gap hypothesis; glass, door leaves and identity not verified. Not free-space evidence.'})
    return results
