"""Record terminal distance, heading error and actual/commanded rotation."""
import json,math,time
from pathlib import Path
import rclpy
from nav_msgs.msg import Path as RosPath,Odometry
from geometry_msgs.msg import Twist
from action_msgs.msg import GoalStatusArray
from tf2_ros import Buffer,TransformListener

rclpy.init();n=rclpy.create_node('goal_alignment_monitor');root=Path(__file__).parent
buf=Buffer();listener=TransformListener(buf,n)
state={'goal':None,'goal_id':None,'active':False,'cmd':Twist(),'omega':0.}
def plan(m):
 if m.poses and state['active']:state['goal']=(m.header.frame_id,m.poses[-1].pose)
def goals(m):
 active=[x for x in m.status_list if x.status in (1,2)];state['active']=bool(active)
 if active:
  uid=bytes(active[-1].goal_info.goal_id.uuid).hex()
  if uid!=state['goal_id']:state['goal_id']=uid;state['goal']=None
subs=[n.create_subscription(RosPath,'/plan',plan,5),n.create_subscription(GoalStatusArray,'/navigate_to_pose/_action/status',goals,10),n.create_subscription(Twist,'/nav_cmd_vel',lambda m:state.update(cmd=m),10),n.create_subscription(Odometry,'/body_odom',lambda m:state.update(omega=m.twist.twist.angular.z),10)]
def yaw(q):return math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
def record():
 if not state['active'] or state['goal'] is None:return
 frame,g=state['goal']
 try:t=buf.lookup_transform(frame,'nav_body',rclpy.time.Time())
 except Exception:return
 e=math.atan2(math.sin(yaw(g.orientation)-yaw(t.transform.rotation)),math.cos(yaw(g.orientation)-yaw(t.transform.rotation)))
 c=state['cmd'];report={'updated':time.time(),'goal_id':state['goal_id'],'distance_m':math.hypot(g.position.x-t.transform.translation.x,g.position.y-t.transform.translation.y),'yaw_error_deg':math.degrees(e),'cmd_x':c.linear.x,'cmd_w':c.angular.z,'measured_w':state['omega'],'goal_yaw_deg':math.degrees(yaw(g.orientation))}
 temporary=root/'goal_alignment_status.tmp';temporary.write_text(json.dumps(report,indent=2));temporary.replace(root/'goal_alignment_status.json')
 with (root/'runtime_logs/goal_alignment.jsonl').open('a') as log:log.write(json.dumps(report)+'\n')
n.create_timer(.2,record)
try:rclpy.spin(n)
finally:n.destroy_node();rclpy.try_shutdown()
