"""Versioned sensor stream with a clock handshake and bounded latest-frame mailbox."""
import struct
import threading

MAGIC=b'NAV2'
HELLO=struct.Struct('!4sd')
HEADER=struct.Struct('!BId')
MAX_PAYLOAD=2_000_000

def write_all(stream,data):
    view=memoryview(data)
    while view:
        count=stream.write(view)
        if not count:raise BrokenPipeError('sensor stream closed')
        view=view[count:]

def read_exact(stream,size):
    chunks=[]
    while size:
        part=stream.read(size)
        if not part:raise EOFError('sensor stream disconnected')
        chunks.append(part);size-=len(part)
    return b''.join(chunks)

def read_hello(stream):
    magic,stamp=HELLO.unpack(read_exact(stream,HELLO.size))
    if magic!=MAGIC:raise ValueError('sensor stream protocol mismatch')
    return stamp

def read_packet(stream):
    channel,length,sent=HEADER.unpack(read_exact(stream,HEADER.size))
    if channel not in (1,2,3,4) or not 0<length<MAX_PAYLOAD:raise ValueError('invalid sensor frame')
    return channel,sent,read_exact(stream,length)

class LatestFrames:
    def __init__(self):
        self.lock=threading.Lock();self.pending={};self.replaced=0
    def put(self,channel,value):
        with self.lock:
            if channel in self.pending:self.replaced+=1
            self.pending[channel]=value
    def take(self):
        with self.lock:
            result=self.pending;self.pending={}
            return result
