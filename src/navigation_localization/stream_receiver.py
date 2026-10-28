from project_config import remote_file, ssh_command
from pathlib import Path
import time,zlib,json,subprocess,threading
import numpy as np,rclpy
from rclpy.serialization import deserialize_message
from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
from sensor_msgs.msg import LaserScan,PointCloud2
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_msgs.msg import TFMessage
from builtin_interfaces.msg import Time
from drivers.stream_protocol import LatestFrames,read_hello,read_packet
from clock_sync import RemoteClock,ClockSync

rclpy.init();n=rclpy.create_node('navigation_live_bridge')
pubs={1:n.create_publisher(LaserScan,'/scan',5),2:n.create_publisher(Odometry,'/odom',10),3:n.create_publisher(PointCloud2,'/obstacle_points',2),4:n.create_publisher(PointCloud2,'/clearing_points',2)}
tfpub=n.create_publisher(TFMessage,'/tf',100)
staticpub=n.create_publisher(TFMessage,'/tf_static',QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL))
tf=TransformStamped();tf.header.frame_id='nav_base';tf.child_frame_id='nav_scan';tf.transform.rotation.w=1.;staticpub.publish(TFMessage(transforms=[tf]))
root=Path(__file__).parent
clock=RemoteClock();clock_sync=ClockSync(clock)
mailbox=LatestFrames();counts={};published={};dropped={};status={'connection':'connecting'};closed=threading.Event();proc=None

def receive():
    global proc
    while not closed.is_set():
        try:
            proc=subprocess.Popen(ssh_command('aidlux', ['python3', '-u', remote_file('aidlux', 'drivers', 'stream_sender.py')], ros=True, timeout=10),stdout=subprocess.PIPE)
            remote_clock=read_hello(proc.stdout)
            # Bootstrap from sender wall time; independent pings recalibrate every 10s.
            local_clock=time.time();local_mono=time.monotonic();clock.prime(remote_clock,local_mono)
            status.update(connection='connected',clock_translation_s=local_clock-remote_clock)
            while not closed.is_set():
                channel,sent,payload=read_packet(proc.stdout)
                # Monotonic elapsed time also tolerates local wall-clock adjustments.
                remote_now=clock.now()
                counts[channel]=counts.get(channel,0)+1
                mailbox.put(channel,(payload,remote_now,sent,time.monotonic()))
        except (EOFError,OSError,ValueError) as exc:
            status.update(connection='reconnecting',error=str(exc));print('扫描连接中断，重新连接:',exc,flush=True)
        finally:
            if proc is not None:
                proc.terminate()
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        closed.wait(1)

thread=threading.Thread(target=receive,daemon=True);thread.start();last=0.
try:
    while rclpy.ok():
        for channel,(payload,remote_now,sent,received_mono) in mailbox.take().items():
            m=deserialize_message(zlib.decompress(payload),{1:LaserScan,2:Odometry,3:PointCloud2,4:PointCloud2}[channel])
            t=m.header.stamp.sec+m.header.stamp.nanosec/1e9
            sensor_age,transport_age=clock.sensor_age(t,sent,remote_now,time.monotonic()-received_mono)
            status.setdefault('sensor_age_s',{})[str(channel)]=sensor_age
            status.setdefault('transport_age_s',{})[str(channel)]=transport_age
            if sensor_age is None or not -.05<=sensor_age<.7:
                dropped[channel]=dropped.get(channel,0)+1;continue
            local=n.get_clock().now().nanoseconds*1e-9-sensor_age
            m.header.stamp=Time(sec=int(local),nanosec=int((local-int(local))*1e9))
            pubs[channel].publish(m);published[channel]=published.get(channel,0)+1
            if channel==2:
                tf=TransformStamped();tf.header=m.header;tf.child_frame_id=m.child_frame_id;tf.transform.translation.x=m.pose.pose.position.x;tf.transform.translation.y=m.pose.pose.position.y;tf.transform.rotation=m.pose.pose.orientation;tfpub.publish(TFMessage(transforms=[tf]))
            elif channel==1:np.savez(root/'live_scan.npz',ranges=np.array(m.ranges),angle_min=m.angle_min,angle_increment=m.angle_increment,stamp=local)
        rclpy.spin_once(n,timeout_sec=.005)
        if time.monotonic()-last>1:
            report=dict(status,clock_sync=clock.snapshot(),received=counts.copy(),published=published.copy(),dropped_stale=dropped.copy(),replaced_pending=mailbox.replaced,updated=time.time())
            temporary=root/'bridge_status.tmp';temporary.write_text(json.dumps(report));temporary.replace(root/'bridge_status.json');last=time.monotonic()
finally:
    closed.set();clock_sync.close()
    if proc is not None:proc.terminate()
    thread.join(timeout=3);n.destroy_node();rclpy.try_shutdown()
