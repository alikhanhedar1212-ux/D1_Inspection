"""Pure guards shared by the Firefly receiver and its offline tests."""
import fcntl,math,queue
from pathlib import Path

class ReceiverLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def acquire(self):
        self.file=self.path.open('a+')
        try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close();self.file=None
            raise RuntimeError('已有速度接收器运行，拒绝创建重复发布器')
        return self
    def close(self):
        if self.file is not None:self.file.close();self.file=None

class InputWatchdog:
    def __init__(self,started):self.started=started;self.received=None;self.sent=None;self.base=None
    def receive(self,sent,now):
        if not math.isfinite(sent):raise ValueError('invalid sender time')
        if self.base is None or self.base[1]+sent-self.base[0]>now:
            self.base=(sent,now)
        self.sent=sent;self.received=now
    def age(self,now):
        if self.received is None:return now-self.started
        return max(now-self.received,now-(self.base[1]+self.sent-self.base[0]))
    def fresh(self,now):return self.received is not None and self.age(now)<.35
    def expired(self,now):return self.age(now)>1.5

class LatestTelemetry:
    def __init__(self):self.queue=queue.Queue(maxsize=1)
    def put(self,item):
        try:self.queue.put_nowait(item)
        except queue.Full:
            try:self.queue.get_nowait()
            except queue.Empty:pass
            try:self.queue.put_nowait(item)
            except queue.Full:pass
