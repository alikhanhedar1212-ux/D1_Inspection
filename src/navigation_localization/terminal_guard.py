"""Stop terminal rotation that fails to converge; never generates motion."""
import math

class TerminalRotationGuard:
    def __init__(self,position_tolerance=.3,yaw_tolerance=math.radians(10)):
        self.position_tolerance=position_tolerance;self.yaw_tolerance=yaw_tolerance
        self.reset()
    def reset(self):
        self.goal=None;self.started=None;self.progress=None;self.best=None
    def update(self,goal,distance,yaw_error,linear_speed,angular_speed,now):
        if goal!=self.goal:
            self.reset();self.goal=goal
        if not all(math.isfinite(v) for v in (distance,yaw_error,linear_speed,angular_speed,now)):
            return '末端转向反馈异常，已停车'
        if abs(linear_speed)>.03:
            self.started=None;self.progress=None;self.best=None
            return None
        error=abs(yaw_error)
        if self.started is None:
            if distance>self.position_tolerance or error<=self.yaw_tolerance or abs(angular_speed)<.02:return None
            self.started=self.progress=now;self.best=error
        if distance>self.position_tolerance+.3:
            return '末端转向位置偏离，已停车，请重新规划'
        if error<self.best-math.radians(3):
            self.best=error;self.progress=now
        if error<=self.yaw_tolerance:
            # Position must also be valid before considering this alignment done.
            if distance<=self.position_tolerance:
                self.started=None;self.progress=None;self.best=None
            elif now-self.started>30:return '位置和朝向未同时达标，已停车'
            return None
        if now-self.started>=30:return '末端转向超过30秒，已停车'
        if now-self.progress>=10:return '末端转向10秒无改善，已停车'
        return None
