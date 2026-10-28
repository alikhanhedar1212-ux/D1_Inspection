"""Continuously estimate a remote wall clock against the local monotonic clock."""
from project_config import remote_file, ssh_command
import selectors,subprocess,threading,time

class RemoteClock:
    def __init__(self,monotonic=time.monotonic):
        self.monotonic=monotonic;self.lock=threading.Lock();self.anchor=None
        self.changed=threading.Event();self.sync_count=0;self.rtt=None;self.error=None
    def prime(self,remote_wall,local_mono):
        with self.lock:
            if self.anchor is None:self.anchor=(float(remote_wall),float(local_mono))
    def synchronize(self,remote_wall,before,after):
        if not 0<=after-before<=.5:raise ValueError('clock ping RTT too large')
        with self.lock:
            self.anchor=(float(remote_wall),(before+after)/2);self.sync_count+=1;self.rtt=after-before;self.error=None
    def now(self):
        with self.lock:
            if self.anchor is None:raise RuntimeError('remote clock unavailable')
            wall,mono=self.anchor
        return wall+self.monotonic()-mono
    def snapshot(self):
        with self.lock:
            return {'sync_count':self.sync_count,'rtt_s':self.rtt,'error':self.error,'last_sync_age_s':None if self.anchor is None else self.monotonic()-self.anchor[1]}
    def sensor_age(self,sensor_stamp,sent_wall,remote_now,elapsed=0.):
        transport=remote_now-sent_wall
        if transport<-.02 or transport>.4:self.changed.set()
        # A clock jump triggers a new independent ping; never relabel the old frame.
        if transport<-.02:return None,transport
        return sent_wall-sensor_stamp+max(0.,transport)+elapsed,transport

class ClockSync:
    def __init__(self,clock):
        self.clock=clock;self.closed=threading.Event();self.proc=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def line(self,selector,timeout):
        if not selector.select(timeout):raise TimeoutError('clock probe timeout')
        line=self.proc.stdout.readline()
        if not line:raise EOFError('clock probe disconnected')
        return line.strip()
    def run(self):
        while not self.closed.is_set():
            selector=None
            try:
                self.proc=subprocess.Popen(ssh_command('aidlux', ['python3', '-u', remote_file('aidlux', 'navigation_localization', 'clock_probe.py')], timeout=5),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
                selector=selectors.DefaultSelector();selector.register(self.proc.stdout,selectors.EVENT_READ)
                if self.line(selector,10)!='CLOCK_READY':raise ValueError('invalid clock probe hello')
                while not self.closed.is_set():
                    # Three short pings; use the least congested round trip.
                    observations=[]
                    for _ in range(3):
                        before=time.monotonic();self.proc.stdin.write('now\n');self.proc.stdin.flush()
                        remote=float(self.line(selector,3));after=time.monotonic();observations.append((after-before,remote,before,after))
                    _,remote,before,after=min(observations)
                    self.clock.synchronize(remote,before,after)
                    self.clock.changed.clear()
                    end=time.monotonic()+10
                    while not self.closed.is_set() and not self.clock.changed.wait(.1) and time.monotonic()<end:pass
                    self.closed.wait(.1)
            except (OSError,ValueError,EOFError,TimeoutError) as exc:
                self.clock.error=str(exc)
            finally:
                if selector is not None:selector.close()
                if self.proc is not None:
                    self.proc.terminate()
                    try:self.proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
            self.closed.wait(1)
    def close(self):
        self.closed.set();self.clock.changed.set()
        if self.proc is not None:self.proc.terminate()
        self.thread.join(timeout=3)
