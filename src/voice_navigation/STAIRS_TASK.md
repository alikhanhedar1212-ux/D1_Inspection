# 下楼准备任务：只到楼梯前平台

触发：先唤醒“太乙真人”，再说“下楼”。终点为平台中央、朝向下行楼梯；本阶段不进入任何台阶。

流程：完整运行前检查 → 二维导航到1号点 → 停车 → 请求三维导航准备、校验实时定位 → 玻璃门“请帮我开门” → 播放结束后等待5秒 → “确认是否已开门” → 只接受独立“确认” → 三维导航到楼梯门等待点并停车 → 重复请求、5秒等待和询问 → 再次收到独立“确认” → 导航到平台中央 → 停车锁零。

已知玻璃门约在1号点前0.8米；精确门位置、等待净空需现场校验。终点意图已由用户确认，暂用尺寸模型局部坐标(5.9,-1.0,0)、yaw=pi；实际坐标尚未标定。1号点及原二维地图、Nav2配置均不修改。

## 当前可用程度

- 命令解析、两次独立确认、播报后5秒计时、取消、迟到结果过滤和到终点停车的状态机已实现。
- 42项任务及原有语音相关测试通过，完整任务在模拟中结束于平台，没有下台阶动作；模拟不是实机证据。
- 开门两句提示在AidLux用预装libespeak-ng本地生成，普通话cmn，经既有USB扬声器播放；保留电脑音频备份。既有唤醒、导航回复音频不变。
- 实机执行尚未启用。stairs_task_config.json中execution_enabled=false，三维定位/控制/坐标对齐及实际停靠点未验证，检查会在机器狗移动前拒绝任务。
- 新代码尚未重启语音监听并实走。仅播放提示不触发任何运动。

## 三维实时后端接口（已部署，尚未现场验收）

运行于语音节点的ROS域93，需提供：
- /stairs_mission/check_ready，std_srvs/Trigger：检查3D控制、实时定位、避障、当前步态和停靠点是否可用；不能只因离线地图打开就返回成功。
- /stairs_mission/prepare_3d，std_srvs/Trigger：在停稳后切换输入/定位/控制链路；就绪后才返回成功。
- /stairs_mission/stop，std_srvs/Trigger：立即停车、取消3D目标并锁零，确认停止后返回。
- /stairs_mission/navigate_to_pose，nav2_msgs/NavigateToPose：仅接收已标定stairs_design坐标中的平地目标，持续保证定位、避障、通信和停步保护。
- 新鲜的stairs_design→stairs_body TF（语音域93；可视化域96使用nav_body）；禁止用未经校验的静态TF冒充实时定位。

这些接口现由 stairs_mapping/realtime/live_navigation.py 提供。默认仅显示与规划，运动输出关闭；check_ready 不会因此返回可执行。实时激光里程计需在1号点人工初始化并核对叠图，不具备全局自动重定位。详见 ../stairs_mapping/realtime/README.md。

## 测试

python3 -m unittest -v test_stairs_task test_commands test_wake test_audio_transport test_home_target test_recognition
python3 simulate_stairs_task.py

simulate_stairs_task.py不启动ROS、不连接机器狗、不播放语音、不发送速度，使用模拟时间演示完整流程。


双向逐次通行确认（2026-10-16）
- 语音命令“进1号门”“出1号门”“进2号门”“出2号门”各自建立独立通行任务。
- 到本侧等待点并完成停车后，请人开门，等待5秒，询问是否同意本次通行；询问播放完毕后仅独立“确认”有效。
- 确认只放行当前门；通过到达对侧等待点、取消、停止、定位失效均清除许可；15秒未发起通行则确认过期。
- 本侧及对侧停靠位姿仍需现场标定，execution_enabled 保持 false。代码修改不代表已启用实机自动通行。
