"""Require fresh measured standstill before announcing a door wait."""
import math


class DoorWaitGuard:
    def __init__(self):
        self.last_stamp = None
        self.still_since = None

    def observe(self, stamp, vx, vy, omega, now, monotonic):
        valid = all(math.isfinite(x) for x in (stamp, vx, vy, omega))
        fresh = valid and -.05 <= now - stamp < .7
        continuous = self.last_stamp is not None and 0 < stamp - self.last_stamp < .7
        still = fresh and math.hypot(vx, vy) < .03 and abs(omega) < .05
        if not still:
            self.still_since = None
        elif self.still_since is None or not continuous:
            self.still_since = monotonic
        self.last_stamp = stamp if fresh else None

    def ready(self, now, monotonic):
        return (self.last_stamp is not None and -.05 <= now - self.last_stamp < .7
                and self.still_since is not None and monotonic - self.still_since >= .6)
