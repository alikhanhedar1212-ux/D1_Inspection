from project_config import map_path
from pathlib import Path
import json,time,yaml,rclpy
from rclpy.action import ActionClient
from nav2_msgs.action import ComputePathToPose
from rcl_interfaces.srv import GetParameters,SetParameters
from rcl_interfaces.msg import Parameter,ParameterValue,ParameterType
r=Path(__file__).parent;rclpy.init();n=rclpy.create_node('shifted_waypoint_check')
def wait(f):
 rclpy.spin_until_future_complete(n,f,timeout_sec=15);assert f.done();return f.result()
params={}
for node in ['/global_costmap/global_costmap','/local_costmap/local_costmap']:
 c=n.create_client(SetParameters,node+'/set_parameters');assert c.wait_for_service(timeout_sec=5);v=ParameterValue(type=ParameterType.PARAMETER_DOUBLE,double_value=.3);req=SetParameters.Request(parameters=[Parameter(name='inflation_layer.inflation_radius',value=v)]);assert wait(c.call_async(req)).results[0].successful
 c=n.create_client(GetParameters,node+'/get_parameters');assert c.wait_for_service(timeout_sec=5);value=wait(c.call_async(GetParameters.Request(names=['inflation_layer.inflation_radius']))).values[0].double_value;assert abs(value-.3)<1e-8;params[node]=value
client=ActionClient(n,ComputePathToPose,'/compute_path_to_pose');assert client.wait_for_server(timeout_sec=5);plans=[]
for w in yaml.safe_load((map_path('waypoints.yaml')).read_text())['waypoints']:
 if w['id'] not in [1,2,6]:continue
 g=ComputePathToPose.Goal();g.goal.header.frame_id='map';g.goal.pose.position.x=w['x'];g.goal.pose.position.y=w['y'];g.goal.pose.orientation.w=1.;g.planner_id='GridBased';h=wait(client.send_goal_async(g));assert h.accepted;res=wait(h.get_result_async());assert res.status==4;plans.append({'id':w['id'],'x':w['x'],'y':w['y'],'status':res.status,'path_poses':len(res.result.path.poses)})
result={'inflation':params,'plans':plans};(r/'shifted_waypoint_check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));n.destroy_node();rclpy.try_shutdown()
