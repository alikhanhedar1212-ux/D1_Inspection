"""Run on AidLux. Slow network never queues a history of sensor messages."""
import os,time,zlib,threading
import rclpy
from rclpy.serialization import serialize_message
from rclpy.qos import QoSProfile,ReliabilityPolicy
from sensor_msgs.msg import LaserScan,PointCloud2
from nav_msgs.msg import Odometry
from stream_protocol import HELLO,MAGIC,HEADER,LatestFrames,write_all

stream=os.fdopen(os.dup(1),'wb',buffering=0);os.dup2(2,1)
write_all(stream,HELLO.pack(MAGIC,time.time()))
rclpy.init();n=rclpy.create_node('navigation_preview_sender')
mailbox=LatestFrames();closed=threading.Event()
qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.BEST_EFFORT)
subs=[n.create_subscription(typ,topic,lambda m,c=channel:mailbox.put(c,m),qos)
      for channel,typ,topic in [(1,LaserScan,'/nav/scan'),(2,Odometry,'/nav/odom'),(3,PointCloud2,'/nav/obstacle_points')]]
def writer():
    try:
        while not closed.is_set():
            batch=mailbox.take()
            for channel in (2,1,3):
                if channel not in batch:continue
                m=batch[channel]
                stamp=m.header.stamp.sec+m.header.stamp.nanosec/1e9
                if not -.05<time.time()-stamp<.7:continue
                payload=zlib.compress(serialize_message(m),1)
                write_all(stream,HEADER.pack(channel,len(payload),time.time())+payload)
            closed.wait(.005)
    except (BrokenPipeError,OSError):closed.set()
thread=threading.Thread(target=writer,daemon=True);thread.start()
try:
    while rclpy.ok() and not closed.is_set():rclpy.spin_once(n,timeout_sec=.1)
finally:closed.set();n.destroy_node();rclpy.try_shutdown()
