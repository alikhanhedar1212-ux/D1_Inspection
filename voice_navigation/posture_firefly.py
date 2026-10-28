"""One-shot normal posture commands through the existing ecal2ros bridge."""
import argparse
import json
import math
import subprocess
from pathlib import Path
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from robots_dog_msgs.msg import HighLevelCmd, HighLevelRobotState, McModeCmd, McState


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['stand', 'lie_down', 'greet'])
    parser.add_argument('--check', action='store_true', help='Inspect readiness without publishing commands')
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node('voice_posture_command')
    state = {}
    def mode(message):
        state.update(mode=message.state, mode_time=time.monotonic())
    def body(message):
        state.update(body=message, body_time=time.monotonic())
    subscriptions = [node.create_subscription(McState, '/arc/mc_state', mode, 10),
                     node.create_subscription(HighLevelRobotState, '/highlevel_robotstate', body, qos_profile_sensor_data)]
    publisher = node.create_publisher(HighLevelCmd, '/highlevel_cmd', 10)
    mode_publisher = node.create_publisher(McModeCmd, '/arc/mc_mode_cmd', 10)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
            if 'body' in state and 'mode' in state and publisher.get_subscription_count():
                break
        if 'body' not in state or 'mode' not in state or not publisher.get_subscription_count():
            raise RuntimeError('底层姿态接口或状态反馈不可用')
        if state['mode'] in (McState.STATE_CHARGING, McState.STATE_FAILURE):
            raise RuntimeError('充电或故障模式不执行姿态动作')
        def stationary():
            b = state['body']
            values = (b.vel.x, b.vel.y, b.vel.z, b.gyro.z)
            return (time.monotonic() - state['body_time'] < .7
                    and time.monotonic() - state['mode_time'] < 1
                    and all(math.isfinite(v) for v in values)
                    and max(abs(v) for v in values[:3]) < .05 and abs(values[3]) < .10)
        if args.check:
            if args.action == 'greet':
                subprocess.run([str(Path(__file__).with_name('greet_native')), '--check'],
                               check=True, timeout=8)
                refresh_until = time.monotonic() + .3
                while time.monotonic() < refresh_until:
                    rclpy.spin_once(node, timeout_sec=.02)
            print(json.dumps({'checked': True, 'mode': state['mode'], 'stationary': stationary()}))
            return
        if args.action == 'greet' and state['mode'] == McState.STATE_NAV_VEL_CTRL:
            raise RuntimeError('打招呼需先用手柄进入实验室模式并站稳，不从导航模式自动切换')
        # Navigation is already canceled and latched at zero by the local caller.
        if state['mode'] == McState.STATE_NAV_VEL_CTRL:
            request = McModeCmd()
            request.stamp = node.get_clock().now().to_msg()
            request.mode = McModeCmd.STANDBY
            mode_publisher.publish(request)
        deadline = time.monotonic() + 5
        quiet_since = None
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
            if stationary() and state['mode'] != McState.STATE_NAV_VEL_CTRL:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= .5:
                    break
            else:
                quiet_since = None
        else:
            raise RuntimeError('未确认机器狗静止，不执行姿态动作')
        if state['mode'] in (McState.STATE_CHARGING, McState.STATE_FAILURE):
            raise RuntimeError('充电或故障模式不执行姿态动作')
        if args.action == 'greet':
            # XG SDKCmd mapped 1/11 to stand 1/10 in the recorded voice test.
            # Use the AppCmd channel confirmed during successful RB+Y instead.
            process = subprocess.Popen([str(Path(__file__).with_name('greet_native'))])
            deadline = time.monotonic() + 24
            try:
                while process.poll() is None:
                    rclpy.spin_once(node, timeout_sec=.05)
                    if (time.monotonic() > deadline
                            or time.monotonic()-state['body_time'] > .7
                            or time.monotonic()-state['mode_time'] > 1
                            or state['mode'] in (McState.STATE_CHARGING, McState.STATE_FAILURE,
                                                 McState.STATE_NAV_VEL_CTRL)):
                        process.terminate()
                        raise RuntimeError('动作期间状态中断或模式改变，停止打招呼程序')
                if process.returncode:
                    raise RuntimeError('未确认进入打招呼状态并返回站立，不自动重试')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            return
        # Existing normal stand / lie-down interface.
        command = HighLevelCmd()
        command.control_mode = 1 if args.action == 'stand' else 51
        command.motion_mode = 0
        print(json.dumps({'sent': True, 'action': args.action,
                          'control_mode': command.control_mode, 'motion_mode': 0}), flush=True)
        for _ in range(3):
            publisher.publish(command)
            rclpy.spin_once(node, timeout_sec=.1)
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
