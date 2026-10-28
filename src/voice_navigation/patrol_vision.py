"""Recognize the supplied printed images, never infer a missing item from stale video."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).parent / 'patrol_assets'
SIGNS = ('forward', 'left', 'right', 'uturn')


def arrow_mask(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (90, 70, 35), (140, 255, 255))
    contours, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    board = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(board)
    if min(w, h) < 35 or not .55 < w / h < 1.8:
        return None
    roi = hsv[y:y+h, x:x+w]
    white = cv2.inRange(roi, (0, 0, 145), (179, 95, 255))
    # Remove the border ring and exterior corners before finding the arrow.
    white[:int(h*.09)] = 0
    white[int(h*.91):] = 0
    white[:, :int(w*.09)] = 0
    white[:, int(w*.91):] = 0
    cs, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    arrow = max(cs, key=cv2.contourArea)
    if cv2.contourArea(arrow) < w*h*.06:
        return None
    a, b, c, d = cv2.boundingRect(arrow)
    mask = np.zeros_like(white)
    cv2.drawContours(mask, [arrow], -1, 255, -1)
    # Preserve orientation; do not rotate or mirror a road sign.
    return cv2.resize(mask[b:b+d, a:a+c], (96, 96), interpolation=cv2.INTER_NEAREST) > 0


class Detector:
    def __init__(self):
        self.signs = {name: arrow_mask(cv2.imread(str(ROOT/(name+'.png')))) for name in SIGNS}
        self.sift = cv2.SIFT_create(nfeatures=1800)
        image = cv2.imread(str(ROOT/'extinguisher.png'))
        image = cv2.resize(image, (640, 640))
        self.keypoints, self.descriptors = self.sift.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)

    def detect(self, frame, kind):
        if kind == 'sign':
            mask = arrow_mask(frame)
            if mask is None:
                return None, {}
            scores = sorted(((float(np.logical_and(mask, ref).sum()/max(1, np.logical_or(mask, ref).sum())), name)
                             for name, ref in self.signs.items()), reverse=True)
            best, name = scores[0]
            good = best >= .75 and best-scores[1][0] >= .10
            return (name if good else None), dict(scores=scores)
        kp, des = self.sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
        if des is None:
            return None, {'inliers': 0}
        pairs = cv2.BFMatcher().knnMatch(self.descriptors, des, k=2)
        matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .68*b.distance]
        if len(matches) < 10:
            return None, {'matches': len(matches)}
        src = np.float32([self.keypoints[m.queryIdx].pt for m in matches])
        dst = np.float32([kp[m.trainIdx].pt for m in matches])
        h, inside = cv2.findHomography(src, dst, cv2.RANSAC, 3)
        count = int(inside.sum()) if inside is not None else 0
        valid = False
        if h is not None and count >= 10 and count/len(matches) >= .6:
            polygon = cv2.perspectiveTransform(np.float32([[[0,0],[639,0],[639,639],[0,639]]]), h)[0]
            area = abs(cv2.contourArea(polygon))
            coverage = abs(cv2.contourArea(cv2.convexHull(src[inside.ravel().astype(bool)])))/(640*640)
            valid = (cv2.isContourConvex(polygon) and 900 < area < frame.shape[0]*frame.shape[1]*1.5 and coverage > .04)
        return ('extinguisher' if valid else None), {'matches':len(matches), 'inliers':count}


class StableDetection:
    def __init__(self):
        self.label = None
        self.count = 0

    def update(self, label):
        self.count = self.count+1 if label is not None and label == self.label else int(label is not None)
        self.label = label
        return label if self.count >= 3 else None
