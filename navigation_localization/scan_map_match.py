"""Global scan matching. Coordinates describe nav_scan/nav_base, not nav_body."""
from pathlib import Path
import math
import numpy as np
import yaml
from PIL import Image
from scipy.ndimage import distance_transform_edt


def angle_delta(a, b):
    return math.atan2(math.sin(a-b), math.cos(a-b))


class Matcher:
    def __init__(self, config):
        config = Path(config)
        m = yaml.safe_load(config.read_text())
        if abs(m['origin'][2]) > 1e-6:
            raise ValueError('Rotated map origins are unsupported')
        grid = np.flipud(np.asarray(Image.open(config.parent / m['image'])))
        probability = grid / 255. if m.get('negate', 0) else 1-grid / 255.
        self.free = probability < m['free_thresh']
        occupied = probability > m['occupied_thresh']
        self.res = float(m['resolution'])
        self.origin = np.array(m['origin'][:2])
        self.field = distance_transform_edt(~occupied) * self.res
        self.height, self.width = grid.shape
        clearance = distance_transform_edt(self.free) * self.res
        yy, xx = np.indices(grid.shape)
        step = max(1, round(.5/self.res))
        ys, xs = np.where((clearance > .25) & (yy % step == 0) & (xx % step == 0))
        self.positions = self.origin + np.column_stack((xs+.5, ys+.5))*self.res

    def points(self, ranges, angle_min, increment):
        ranges = np.asarray(ranges)
        ids = np.flatnonzero(np.isfinite(ranges) & (ranges > .6) & (ranges < 15))
        if len(ids) < 80:
            raise ValueError('有效雷达点不足，等待更多扫描')
        ids = ids[np.linspace(0, len(ids)-1, min(160, len(ids))).astype(int)]
        angles = angle_min + ids*increment
        return np.column_stack((np.cos(angles)*ranges[ids], np.sin(angles)*ranges[ids]))

    def scores(self, positions, yaw, points):
        rotation = np.array([[np.cos(yaw), np.sin(yaw)], [-np.sin(yaw), np.cos(yaw)]])
        cells = np.floor((positions[:, None, :] + points @ rotation-self.origin)/self.res).astype(int)
        x, y = cells[:, :, 0], cells[:, :, 1]
        valid = (x >= 0) & (x < self.width) & (y >= 0) & (y < self.height)
        distance = self.field[np.clip(y, 0, self.height-1), np.clip(x, 0, self.width-1)]
        return np.mean(np.exp(-.5*(distance/.2)**2)*valid, axis=1)

    def search(self, points):
        if not len(self.positions):
            raise ValueError('地图中没有足够空旷的定位候选区域')
        coarse = []
        for yaw in np.arange(-np.pi, np.pi, np.pi/36):
            scores = self.scores(self.positions, yaw, points)
            for i in np.argsort(scores)[-8:]:
                coarse.append((float(scores[i]), *self.positions[i], float(yaw)))
        seeds = []
        for p in sorted(coarse, reverse=True):
            if all(np.hypot(p[1]-v[1], p[2]-v[2]) > .8 or abs(angle_delta(p[3], v[3])) > .35 for v in seeds):
                seeds.append(p)
            if len(seeds) == 16:
                break
        refined = []
        offsets = np.array([(x,y) for x in np.arange(-.45,.451,.05) for y in np.arange(-.45,.451,.05)])
        for _, x, y, yaw in seeds:
            positions = np.array([x,y])+offsets
            cells = np.floor((positions-self.origin)/self.res).astype(int)
            valid = (cells[:,0]>=0)&(cells[:,0]<self.width)&(cells[:,1]>=0)&(cells[:,1]<self.height)
            positions, cells = positions[valid], cells[valid]
            positions = positions[self.free[cells[:,1],cells[:,0]]]
            if not len(positions):
                continue
            best = None
            for a in np.arange(yaw-.12, yaw+.121, .01):
                scores = self.scores(positions, a, points)
                i = int(scores.argmax())
                p = (float(scores[i]), *positions[i], angle_delta(a,0))
                if best is None or p[0] > best[0]:
                    best = p
            refined.append(best)
        hypotheses = []
        for p in sorted(refined, reverse=True):
            if all(np.hypot(p[1]-v['x'], p[2]-v['y']) > .8 or abs(angle_delta(p[3],v['yaw'])) > .35 for v in hypotheses):
                hypotheses.append(dict(zip(('score','x','y','yaw'), map(float,p))))
        return hypotheses

    @staticmethod
    def confident(hypotheses):
        return bool(len(hypotheses) > 1 and hypotheses[0]['score'] >= .70
                    and hypotheses[0]['score']-hypotheses[1]['score'] >= .08)
