"""Visit points 1–6 once, dwelling five seconds between successful goals."""
import json
import argparse
import math
import time
from pathlib import Path

import rclpy
import yaml
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from std_srvs.srv import Trigger


ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node('six_point_tour')
    client = ActionClient(node, NavigateToPose, '/navigate_to_pose')
    stop = node.create_client(Trigger, '/stop_navigation')
    completed = []
    if args.resume:
        previous = json.loads((ROOT/'tour_status.json').read_text())
        completed = previous['completed']
        if completed != list(range(1,len(completed)+1)):
            raise ValueError('巡航记录不是连续完成的序列，不能自动续行')
    state = dict(state='starting', completed=completed, dwell_seconds=5)
    handle = None
    last_print = 0.

    def report(**updates):
        state.update(updates, updated=time.time())
        path = ROOT/'tour_status.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        temp.replace(path)

    def wait(future, seconds=10):
        rclpy.spin_until_future_complete(node, future, timeout_sec=seconds)
        if not future.done():
            raise TimeoutError('导航请求响应超时')
        return future.result()

    def bridge_ready(check_localization=True):
        # The running bridge can briefly truncate this file while updating it.
        # Bound retries; missing, stale or invalid status must still stop motion.
        for attempt in range(3):
            try:
                b = json.loads((ROOT/'velocity_bridge_status.json').read_text())
                break
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
                time.sleep(.01)
        if time.time()-b['updated'] > 3:
            raise RuntimeError('运动连接状态超时')
        if check_localization:
            c = b.get('covariance')
            if b.get('match', 0) < .45 or not c or max(c[:2]) >= .25 or c[2] >= .09:
                raise RuntimeError('实时定位质量不足')
        return b

    def feedback(msg):
        nonlocal last_print
        f = msg.feedback
        p = f.current_pose.pose.position
        report(distance_remaining=float(f.distance_remaining), position=[p.x,p.y])
        if time.monotonic()-last_print > 10:
            print(json.dumps(state, ensure_ascii=False), flush=True)
            last_print = time.monotonic()

    try:
        bridge_ready()
        if not client.wait_for_server(timeout_sec=8):
            raise RuntimeError('导航服务不可用')
        points = {w['id']: w for w in yaml.safe_load((ROOT/'waypoints.yaml').read_text())['waypoints']}
        for point_id in range(len(completed)+1,7):
            bridge_ready()
            waypoint = points[point_id]
            goal = NavigateToPose.Goal()
            goal.pose.header.frame_id = 'map'
            goal.pose.header.stamp = node.get_clock().now().to_msg()
            goal.pose.pose.position.x = float(waypoint['x'])
            goal.pose.pose.position.y = float(waypoint['y'])
            goal.pose.pose.orientation.z = math.sin(waypoint['yaw']/2)
            goal.pose.pose.orientation.w = math.cos(waypoint['yaw']/2)
            report(state='sending', target=waypoint, distance_remaining=None, position=None)
            handle = wait(client.send_goal_async(goal, feedback_callback=feedback))
            if not handle.accepted:
                raise RuntimeError(f'{point_id}号目标被拒绝')
            print(f'已出发：{point_id}号 {waypoint["name"]}', flush=True)
            report(state='executing')
            result = handle.get_result_async()
            deadline = time.monotonic()+240
            while not result.done() and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.2)
                bridge_ready(check_localization=False)
            if not result.done():
                raise TimeoutError(f'{point_id}号导航超时')
            status = result.result().status
            if status != 4:
                raise RuntimeError(f'{point_id}号导航未完成，状态 {status}')
            handle = None
            completed.append(point_id)
            print(f'已到达：{point_id}号 {waypoint["name"]}', flush=True)
            if point_id < 6:
                report(state='dwelling', next_target=point_id+1)
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    rclpy.spin_once(node, timeout_sec=min(.1, max(0.,deadline-time.monotonic())))
                    b = bridge_ready(check_localization=False)
                    if b['reason'] in ('用户停止','运动连接断开'):
                        raise RuntimeError('停留期间收到停止或运动连接中断')
        report(state='succeeded', next_target=None)
        print('巡航完成：1→2→3→4→5→6，每段之间停留5秒', flush=True)
    except BaseException as error:
        if handle is not None:
            try:
                wait(handle.cancel_goal_async(), 5)
            except Exception:
                pass
        if stop.wait_for_service(timeout_sec=3):
            try:
                wait(stop.call_async(Trigger.Request()), 5)
            except Exception:
                pass
        report(state='stopped', error=str(error))
        print('巡航已停止：'+str(error), flush=True)
        raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
