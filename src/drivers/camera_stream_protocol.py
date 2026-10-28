"""Small framed camera protocol; timestamps describe source read, not USB exposure."""
import struct,threading
MAGIC=b'CAM2';HELLO=struct.Struct('!4sd');HEADER=struct.Struct('!IddQ');MAX_IMAGE=2_000_000

def read_exact(stream,size):
    result=[]
    while size:
        chunk=stream.read(size)
        if not chunk:raise EOFError('camera stream disconnected')
        result.append(chunk);size-=len(chunk)
    return b''.join(result)

def write_all(stream,data):
    data=memoryview(data)
    while data:
        count=stream.write(data)
        if not count:raise BrokenPipeError('camera stream closed')
        data=data[count:]

def read_hello(stream):
    magic,clock=HELLO.unpack(read_exact(stream,HELLO.size))
    if magic!=MAGIC:raise ValueError('camera protocol mismatch')
    return clock

def read_frame(stream):
    length,captured,sent,sequence=HEADER.unpack(read_exact(stream,HEADER.size))
    if not 0<length<MAX_IMAGE:raise ValueError('invalid camera frame length')
    return captured,sent,sequence,read_exact(stream,length)

class LatestFrame:
    def __init__(self):self.lock=threading.Lock();self.value=None;self.replaced=0
    def put(self,value):
        with self.lock:
            if self.value is not None:self.replaced+=1
            self.value=value
    def take(self):
        with self.lock:value=self.value;self.value=None;return value
