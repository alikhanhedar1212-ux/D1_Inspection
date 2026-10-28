"""Local SE(2) reference matching. Estimates only; never publishes commands."""
import math

import numpy as np
from scipy.spatial import cKDTree


def body_points(cloud):
    p = np.asarray(cloud, dtype=float)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError('expected Nx3 nav_scan cloud')
    return np.column_stack([-p[:, 1], p[:, 0], p[:, 2]])


def features(body_cloud):
    p = np.asarray(body_cloud, dtype=float)
    p = p[np.isfinite(p).all(axis=1)]
    p = p[(p[:, 0] > .25) & (p[:, 0] < 3.5) & (abs(p[:, 1]) < 2.8)
          & (p[:, 2] > .1) & (p[:, 2] < .8), :2]
    if not len(p):
        return np.empty((0, 2))
    _, ids = np.unique(np.floor(p/.03).astype(int), axis=0, return_index=True)
    return p[ids]


def transform(points, pose):
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return points @ np.array([[c, s], [-s, c]]) + [x, y]


class ReferenceMatcher:
    def __init__(self, body_cloud):
        self.reference = features(body_cloud)
        if len(self.reference) < 80:
            raise ValueError('reference has insufficient nearby structure')
        self.tree = cKDTree(self.reference)
        distances, ids = self.tree.query(self.reference, k=7)
        neighbors = self.reference[ids]
        centered = neighbors-neighbors.mean(axis=1)[:, None, :]
        values, vectors = np.linalg.eigh(np.einsum('nki,nkj->nij', centered, centered)/7)
        self.normals = vectors[:, :, 0]
        self.planar = (distances[:, -1] < .22) & (values[:, 0]/np.maximum(values[:, 1], 1e-9) < .18)

    def _fit(self, source, initial):
        pose = np.array(initial, dtype=float)
        for _ in range(35):
            q = transform(source, pose)
            distances, ids = self.tree.query(q)
            valid = (distances < .18) & self.planar[ids]
            if valid.sum() < 50:
                return None
            n = self.normals[ids[valid]]
            local = q[valid]-pose[:2]
            jacobian = np.column_stack([n, -n[:, 0]*local[:, 1]+n[:, 1]*local[:, 0]])
            residual = np.einsum('ij,ij->i', n, q[valid]-self.reference[ids[valid]])
            weight = np.minimum(1., .03/np.maximum(abs(residual), 1e-9))
            j = jacobian*np.sqrt(weight)[:, None]
            delta = np.linalg.lstsq(j, -residual*np.sqrt(weight), rcond=None)[0]
            if not np.isfinite(delta).all():
                return None
            delta[:2] = np.clip(delta[:2], -.08, .08)
            delta[2] = np.clip(delta[2], -.06, .06)
            pose += delta
            if np.linalg.norm(pose[:2]) > .65 or abs(pose[2]) > math.radians(25):
                return None
            if np.linalg.norm(delta) < 1e-5:
                break
        q = transform(source, pose)
        distances, ids = self.tree.query(q)
        overlap = float(np.mean(distances < .08))
        score = float(np.mean(np.minimum(distances, .2)))
        valid = (distances < .08) & self.planar[ids]
        if valid.sum() < 50:
            return None
        n = self.normals[ids[valid]]
        local = q[valid]-pose[:2]
        j = np.column_stack([n, -n[:, 0]*local[:, 1]+n[:, 1]*local[:, 0]])
        eigenvalues = np.linalg.eigvalsh(j.T@j/len(j))
        return dict(pose=pose, overlap=overlap, mean_capped_distance_m=score,
                    observability_ratio=float(eigenvalues[0]/max(eigenvalues[-1], 1e-9)))

    def match(self, body_cloud):
        source = features(body_cloud)
        rejected = {'state': 'rejected', 'automatic_adjustment_enabled': False}
        if len(source) < 80:
            return dict(rejected, reason='insufficient nearby structure')
        solutions = []
        # Multiple independent starts expose alternative local alignments.
        for x in (-.3, 0., .3):
            for y in (-.3, 0., .3):
                for yaw in (-.2, 0., .2):
                    fit = self._fit(source, (x, y, yaw))
                    if fit is not None:
                        solutions.append(fit)
        if not solutions:
            return dict(rejected, reason='no bounded solution')
        solutions.sort(key=lambda s: s['mean_capped_distance_m'])
        best = solutions[0]
        alternatives = [s for s in solutions[1:]
                        if np.linalg.norm(s['pose'][:2]-best['pose'][:2]) > .12
                        or abs(s['pose'][2]-best['pose'][2]) > math.radians(5)]
        ambiguous = any(s['mean_capped_distance_m'] < best['mean_capped_distance_m']+.012
                        and s['overlap'] > .65 for s in alternatives)
        accepted = (best['overlap'] >= .8 and best['mean_capped_distance_m'] < .04
                    and best['observability_ratio'] > .015 and not ambiguous)
        x, y, yaw = best.pop('pose')
        c, s = math.cos(yaw), math.sin(yaw)
        return dict(best, state='matched_read_only' if accepted else 'rejected',
                    current_pose_in_reference=[float(x), float(y), float(yaw)],
                    reference_goal_in_current_body=[float(-c*x-s*y), float(s*x-c*y), float(-yaw)],
                    ambiguous=ambiguous, automatic_adjustment_enabled=False,
                    reason='local geometry match only; door identity and motion are not authorized'
                    if accepted else 'overlap, residual, geometry observability or ambiguity check failed')
