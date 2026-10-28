"""Pure validation shared by the voice relocalization worker and tests."""
import math


def angle(a):
    return math.atan2(math.sin(a), math.cos(a))


def select_consistent_pose(reports):
    if len(reports) < 3:
        raise ValueError('需要三帧独立扫描')
    for hypotheses in reports:
        if len(hypotheses) < 2:
            raise ValueError('缺少独立次优候选，不能判定定位可靠')
        best, runner_up = hypotheses[:2]
        if not all(math.isfinite(best[k]) for k in ('score', 'x', 'y', 'yaw')):
            raise ValueError('定位候选无效')
        if (not math.isfinite(runner_up['score']) or best['score'] < .70
                or best['score']-runner_up['score'] < .08):
            raise ValueError('扫描匹配不足或定位候选不明确')
    best = reports[-1][0]
    for h in reports:
        if math.hypot(h[0]['x']-best['x'], h[0]['y']-best['y']) > .20 or abs(angle(h[0]['yaw']-best['yaw'])) > .06:
            raise ValueError('三帧扫描定位不一致')
    return dict(best)


def stationary_poses(samples, now):
    if len(samples) < 10:
        return False
    if not all(all(math.isfinite(float(v)) for v in row) for row in samples):
        return False
    if not -.05 <= now-samples[-1][0] < .7:
        return False
    first = samples[0]
    return (samples[-1][0]-first[0] >= .6
            and all(0 < b[0]-a[0] < .7 for a, b in zip(samples, samples[1:]))
            and all(math.hypot(p[1]-first[1], p[2]-first[2]) < .05
                    and abs(angle(p[3]-first[3])) < .04 for p in samples))


def amcl_confirmed(candidate, pose, covariance, scan_score):
    values = list(pose)+list(covariance)+[scan_score]
    return (all(math.isfinite(v) for v in values) and all(0 <= v < .25 for v in covariance[:2])
            and 0 <= covariance[2] < .09 and scan_score >= .70
            and math.hypot(pose[0]-candidate['x'], pose[1]-candidate['y']) <= .35
            and abs(angle(pose[2]-candidate['yaw'])) <= .15)
