"""Stay awake until ten seconds pass without a valid command."""
import threading
import time
from commands import normalize, parse

# The wake phrase is matched after removing ASR token spacing.
WAKE_WORD = '小爱同学'
WAKE_WORDS = {WAKE_WORD}
WAKE_GRAMMAR = ['小爱 同学']


class WakeSession:
    def __init__(self, clock=time.monotonic, window=30):
        self.clock = clock
        self.window = window
        self.phase = 'sleeping'
        self.deadline = 0
        self.lock = threading.RLock()
        self.generation = 0

    def reset(self):
        with self.lock:
            self.generation += 1
            self.phase = 'sleeping'
            self.deadline = 0

    def expire(self):
        with self.lock:
            if self.phase == 'awake' and self.clock() >= self.deadline:
                self.reset()
                return True
            return False

    def reply_finished(self, generation, success=True):
        with self.lock:
            if generation != self.generation or self.phase != 'replying':
                return False
            if success:
                self.phase = 'awake'
                self.deadline = self.clock() + self.window
            else:
                self.reset()
            return success

    def feed(self, text, confidence=1):
        with self.lock:
            self.expire()
            command = parse(text)
            if command and command['action'] == 'stop':
                if self.phase == 'awake':
                    self.deadline = self.clock() + self.window
                else:
                    self.reset()
                return ('command', command)
            if self.phase == 'replying':
                return ('ignored', None)
            if normalize(text).lower() in WAKE_WORDS:
                self.generation += 1
                self.phase = 'replying'
                return ('wake', self.generation)
            if not command:
                return ('ignored', None)
            if self.phase != 'awake':
                return ('needs_wake', None)
            self.deadline = self.clock() + self.window
            return ('command', command)
