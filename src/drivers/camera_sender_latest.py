"""AidLux single camera owner: continuous capture, latest-frame-only 8fps JPEG."""
from project_config import setting
import cv2,os,struct,time,threading,json
from pathlib import Path
from camera_stream_protocol import HELLO,HEADER,MAGIC,LatestFrame,write_all

stream=os.fdopen(os.dup(1),'wb',buffering=0);os.dup2(2,1)
write_all(stream,HELLO.pack(MAGIC,time.time()))
cap=cv2.VideoCapture(setting('camera_device'),cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'));cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,642);cap.set(cv2.CAP_PROP_FPS,30);cap.set(cv2.CAP_PROP_CONVERT_RGB,0);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
if not cap.isOpened():raise RuntimeError('camera cannot open')
latest=LatestFrame();closed=threading.Event();stats={'captured':0,'sent':0,'invalid':0};status=Path(__file__).with_name('camera_stream_status.json')
def capture():
    try:
        while not closed.is_set():
            ok,raw=cap.read();captured=time.time()
            if not ok:closed.wait(.02);continue
            data=raw.tobytes();a=data.find(b'\xff\xd8');b=data.find(b'\xff\xd9',a+2)
            if a<0 or b<0:stats['invalid']+=1;continue
            a=data.rfind(b'\xff\xd8',a,b);stats['captured']+=1
            latest.put((captured,stats['captured'],data[a:b+2]))
    finally:cap.release()
thread=threading.Thread(target=capture,daemon=True);thread.start();last_send=0.;last_report=0.
try:
    while not closed.is_set():
        remaining=.125-(time.monotonic()-last_send)
        if remaining>0:closed.wait(min(remaining,.02));continue
        item=latest.take()
        if item is None:closed.wait(.005);continue
        captured,sequence,data=item
        if time.time()-captured>.5:continue
        # Fixed dimensions; reduce network load without changing map topics.
        import numpy as np
        image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        if image is None:stats['invalid']+=1;continue
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,55])
        if not ok:continue
        payload=encoded.tobytes();sent=time.time();started=time.monotonic()
        write_all(stream,HEADER.pack(len(payload),captured,sent,sequence)+payload)
        stats.update(sent=stats['sent']+1,jpeg_bytes=len(payload),write_seconds=time.monotonic()-started,source_read_age_s=time.time()-captured,replaced=latest.replaced,updated=time.time())
        last_send=time.monotonic()
        if last_send-last_report>1:
            tmp=status.with_suffix('.tmp');tmp.write_text(json.dumps(stats));tmp.replace(status);last_report=last_send
except (BrokenPipeError,OSError):pass
finally:closed.set();thread.join(timeout=2)
