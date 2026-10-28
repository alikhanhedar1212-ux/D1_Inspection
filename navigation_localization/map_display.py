"""Display-only unknown recoloring. Navigation topics are never modified."""
from array import array
import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy


def main():
    rclpy.init()
    node=rclpy.create_node('navigation_map_display')
    qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    subscriptions=[]
    publishers=[]
    for topic in ('/map', '/global_costmap/costmap', '/local_costmap/costmap'):
        publisher=node.create_publisher(OccupancyGrid,topic+'_display',qos)
        publishers.append(publisher)
        def render(message, publisher=publisher):
            display=OccupancyGrid()
            display.header=message.header
            display.info=message.info
            display.data=array('b',(0 if value<0 else value for value in message.data))
            publisher.publish(display)
        subscriptions.append(node.create_subscription(OccupancyGrid,topic,render,qos))
    try:rclpy.spin(node)
    finally:node.destroy_node();rclpy.try_shutdown()


if __name__=='__main__':main()
