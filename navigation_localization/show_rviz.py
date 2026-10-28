import ctypes as c
from PIL import ImageGrab
X=c.CDLL('libX11.so.6');X.XOpenDisplay.argtypes=[c.c_char_p];X.XOpenDisplay.restype=c.c_void_p;d=X.XOpenDisplay(b':1');X.XDefaultRootWindow.argtypes=[c.c_void_p];X.XDefaultRootWindow.restype=c.c_ulong;root=X.XDefaultRootWindow(d)
X.XQueryTree.argtypes=[c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_ulong),c.POINTER(c.POINTER(c.c_ulong)),c.POINTER(c.c_uint)];X.XFetchName.argtypes=[c.c_void_p,c.c_ulong,c.POINTER(c.c_void_p)];X.XFree.argtypes=[c.c_void_p];X.XInternAtom.argtypes=[c.c_void_p,c.c_char_p,c.c_int];X.XInternAtom.restype=c.c_ulong
rp=c.c_ulong();pp=c.c_ulong();children=c.POINTER(c.c_ulong)();count=c.c_uint();X.XQueryTree(d,root,c.byref(rp),c.byref(pp),c.byref(children),c.byref(count));target=None
windows=list(children[:count.value])
for parent in list(windows):
 sub=c.POINTER(c.c_ulong)();n=c.c_uint()
 if X.XQueryTree(d,parent,c.byref(rp),c.byref(pp),c.byref(sub),c.byref(n)):
  windows.extend(sub[:n.value]);X.XFree(sub)
for w in windows:
 p=c.c_void_p()
 if X.XFetchName(d,w,c.byref(p)) and p:
  name=c.string_at(p).decode('utf-8',errors='replace');X.XFree(p)
  if 'navigation_drive' in name:target=w;print(name,w)
X.XFree(children)
class CM(c.Structure):_fields_=[('type',c.c_int),('serial',c.c_ulong),('send_event',c.c_int),('display',c.c_void_p),('window',c.c_ulong),('message_type',c.c_ulong),('format',c.c_int),('data',c.c_long*5)]
class E(c.Union):_fields_=[('client',CM),('pad',c.c_long*24)]
X.XSendEvent.argtypes=[c.c_void_p,c.c_ulong,c.c_int,c.c_long,c.POINTER(E)];X.XFlush.argtypes=[c.c_void_p]
if target:
 def send(atom,values):
  e=E();e.client.type=33;e.client.display=d;e.client.window=target;e.client.message_type=X.XInternAtom(d,atom.encode(),0);e.client.format=32
  for i,v in enumerate(values):e.client.data[i]=v
  X.XSendEvent(d,root,0,(1<<20)|(1<<19),c.byref(e));X.XFlush(d)
 send('_NET_ACTIVE_WINDOW',[1,0,0]);send('_NET_WM_STATE',[1,X.XInternAtom(d,b'_NET_WM_STATE_MAXIMIZED_VERT',0),X.XInternAtom(d,b'_NET_WM_STATE_MAXIMIZED_HORZ',0),1])
else:raise RuntimeError('找不到导航 RViz 窗口')
