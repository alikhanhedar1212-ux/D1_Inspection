"""Receive source-timestamped latest camera frames; shared by RViz and OctoMap."""
from deployment import remote_file, ssh_command
import subprocess,cv2,numpy as np,time,rclpy,json,threading
from pathlib import Path
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from builtin_interfaces.msg import Time
from camera_stream_protocol import LatestFrame,read_hello,read_frame
from navigation_localization.clock_sync import RemoteClock,ClockSync

rclpy.init();node=rclpy.create_node('dog_camera_local');pub=node.create_publisher(Image,'/dog_camera/image_raw',1);bridge=CvBridge()
clock=RemoteClock();clock_sync=ClockSync(clock)
latest=LatestFrame();closed=threading.Event();p=None
status_file=Path(__file__).parent/'navigation_localization/camera_status.json';status={'connection':'connecting','frames':0};last=0.
def receiver():
    global p
    while not closed.is_set():
        try:
            p=subprocess.Popen(ssh_command('aidlux', ['python3', '-u', remote_file('aidlux', '', 'camera_sender_latest.py')], timeout=5),stdout=subprocess.PIPE)
            remote_clock=read_hello(p.stdout);mono=time.monotonic();clock.prime(remote_clock,mono);status.update(connection='streaming',clock_translation_s=time.time()-remote_clock)
            while not closed.is_set():
                captured,sent,sequence,payload=read_frame(p.stdout)
                latest.put((captured,sent,sequence,payload,clock.now(),time.monotonic()))
        except (EOFError,OSError,ValueError) as exc:
            status.update(connection='reconnecting',error=str(exc));print(str(exc),flush=True)
        finally:
            if p is not None:
                p.terminate()
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        closed.wait(1)
thread=threading.Thread(target=receiver,daemon=True);thread.start()
try:
    while rclpy.ok():
        item=latest.take()
        if item:
            captured,sent,sequence,payload,remote_now,received_mono=item
            age,transport_age=clock.sensor_age(captured,sent,remote_now,time.monotonic()-received_mono)
            status.update(source_read_age_s=age,transport_age_s=transport_age,sequence=sequence,replaced_pending=latest.replaced)
            if age is not None and -.05<=age<.7:
                frame=cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_COLOR)
                if frame is not None:
                    frame=cv2.rotate(frame,cv2.ROTATE_180)
                    msg=bridge.cv2_to_imgmsg(frame,'bgr8');stamp=node.get_clock().now().nanoseconds/1e9-age
                    msg.header.stamp=Time(sec=int(stamp),nanosec=int((stamp%1)*1e9));msg.header.frame_id='dog_camera';pub.publish(msg)
                    status.update(frames=status['frames']+1,width=msg.width,height=msg.height,last_frame_received=time.time(),jpeg_bytes=len(payload))
            else:status['dropped_stale']=status.get('dropped_stale',0)+1
        rclpy.spin_once(node,timeout_sec=.005)
        if time.monotonic()-last>1:
            status['updated']=time.time();status['clock_sync']=clock.snapshot();tmp=status_file.with_suffix('.tmp');tmp.write_text(json.dumps(status));tmp.replace(status_file);print(json.dumps(status),flush=True);last=time.monotonic()
finally:
    closed.set();clock_sync.close()
    if p is not None:p.terminate()
    thread.join(timeout=3);node.destroy_node();rclpy.try_shutdown()
