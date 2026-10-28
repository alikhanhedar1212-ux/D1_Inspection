"""Door-gated pre-stairs mission. Effects are acknowledged; no motion here."""
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class Effect:
    token: int
    kind: str
    value: str


class StairsTask:
    TERMINAL = {'idle', 'complete', 'cancelled', 'failed'}

    def __init__(self, clock=time.monotonic, stop_at_first_confirmation=False, first_door_wait_only=False):
        self.clock = clock
        self.stop_at_first_confirmation = stop_at_first_confirmation
        self.first_door_wait_only = first_door_wait_only
        self.lock = threading.RLock()
        self.serial = 0
        self.pending = None
        self.state = 'idle'
        self.deadline = None
        self.door = 0
        self.error = ''
        self.passage = None

    @property
    def active(self):
        return self.state not in self.TERMINAL

    @property
    def awaiting_confirmation(self):
        return self.state in ('door_1_confirm', 'door_2_confirm')

    def _effect(self, state, kind, value):
        self.state = state
        self.serial += 1
        self.pending = Effect(self.serial, kind, value)
        return [self.pending]

    def start_passage(self, door, direction):
        if self.first_door_wait_only:
            raise ValueError('当前仅启用第一扇门前等待，不允许穿门')
        if door not in (1,2) or direction not in ('enter','exit'):
            raise ValueError('无效门编号或通行方向')
        with self.lock:
            if self.active or self.pending is not None:return []
            self.error = '';self.deadline = None;self.door = door
            self.passage = {'door':door,'direction':direction}
            return self._effect('preflight','check','all_stages')

    def start(self):
        with self.lock:
            if self.active or self.pending is not None:
                return []
            self.error = ''
            self.passage = None
            self.door = 0
            self.deadline = None
            return self._effect('preflight', 'check', 'all_stages')

    def done(self, token, success=True, reason=''):
        with self.lock:
            if self.pending is None or token != self.pending.token:
                return []
            self.pending = None
            if not success:
                if self.state in ('failed', 'cancelled'):
                    self.state = 'failed'
                    self.error = reason or '停止反馈失败'
                    return []
                self.error = reason or '阶段执行失败'
                return self._effect('failed', 'stop', 'all_motion')
            if self.state == 'passage_approach':
                return self._effect('passage_stop','stop','all_motion')
            if self.state == 'passage_stop':
                return self._effect(f'door_{self.door}_request','speak','request_open_door')
            if self.state == 'passage_cross':
                return self._effect('stop_fixed','stop','all_motion')
            if self.state == 'preflight' and self.passage:
                side = 'outside' if self.passage['direction']=='enter' else 'inside'
                return self._effect('passage_approach','navigate_3d',f'door_{self.door}_{side}_wait')
            if self.state == 'preflight':
                return self._effect('go_1', 'navigate_2d', 'door_wait')
            if self.state == 'go_1':
                return self._effect('stop_1', 'stop', 'all_motion')
            if self.state == 'stop_1':
                if self.first_door_wait_only:
                    self.door = 1
                    return self._effect('door_1_request', 'speak', 'request_open_door')
                return self._effect('switch_3d', 'switch', 'localized_3d')
            if self.state == 'switch_3d':
                self.door = 1
                return self._effect('door_1_request', 'speak', 'request_open_door')
            if self.state in ('door_1_request', 'door_2_request'):
                if self.first_door_wait_only:
                    self.state = 'door_1_wait'
                    self.deadline = None
                    return []
                self.deadline = self.clock() + 5.0
                self.state = f'door_{self.door}_delay'
                return []
            if self.state in ('door_1_question', 'door_2_question'):
                self.state = f'door_{self.door}_confirm'
                return []
            if self.state == 'go_door_2':
                return self._effect('stop_door_2', 'stop', 'all_motion')
            if self.state == 'stop_door_2':
                self.door = 2
                return self._effect('door_2_request', 'speak', 'request_open_door')
            if self.state == 'go_fixed':
                return self._effect('stop_fixed', 'stop', 'all_motion')
            if self.state == 'stop_fixed':
                self.state = 'complete'
            return []

    def tick(self):
        with self.lock:
            if self.state in ('door_1_delay', 'door_2_delay') and self.clock() >= self.deadline:
                self.deadline = None
                key = f'permit_door_{self.door}_{self.passage["direction"]}' if self.passage else 'confirm_door_open'
                return self._effect(f'door_{self.door}_question', 'speak', key)
            return []

    def confirm(self):
        with self.lock:
            if self.passage and self.awaiting_confirmation:
                side = 'inside' if self.passage['direction']=='enter' else 'outside'
                return self._effect('passage_cross','navigate_3d',f'door_{self.door}_{side}_wait')
            if self.state == 'door_1_confirm' and self.stop_at_first_confirmation:
                return self._effect('stop_fixed', 'stop', 'all_motion')
            if self.state == 'door_1_confirm':
                return self._effect('go_door_2', 'navigate_3d', 'door_2_wait')
            if self.state == 'door_2_confirm':
                return self._effect('go_fixed', 'navigate_3d', 'stairs_platform_center')
            return []

    def cancel(self, reason='语音停止或连接中断'):
        with self.lock:
            if not self.active:
                return []
            self.deadline = None
            self.error = reason
            return self._effect('cancelled', 'stop', 'all_motion')

    def snapshot(self):
        with self.lock:
            return {'state': self.state, 'door': self.door, 'active': self.active,
                    'awaiting_confirmation': self.awaiting_confirmation, 'error': self.error, 'passage': self.passage}
