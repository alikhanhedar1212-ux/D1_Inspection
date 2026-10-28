from project_config import setting
import cv2,os,sys,struct,time
stream=os.fdopen(os.dup(1),'wb',buffering=0);os.dup2(2,1)
cap=cv2.VideoCapture(setting('camera_device'),cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'));cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,642);cap.set(cv2.CAP_PROP_FPS,30);cap.set(cv2.CAP_PROP_CONVERT_RGB,0);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
if not cap.isOpened():raise RuntimeError('摄像头无法打开')
last=0
try:
 while True:
  ok,raw=cap.read()
  if not ok: time.sleep(.05);continue
  data=raw.tobytes();a=data.find(b'\xff\xd8');b=data.find(b'\xff\xd9',a+2)
  if a<0 or b<0:continue
  if time.monotonic()-last<.1:continue
  last=time.monotonic();jpeg=data[a:b+2];stream.write(struct.pack('!I',len(jpeg))+jpeg)
finally:cap.release()
