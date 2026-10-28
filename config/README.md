# 项目配置

此目录独立于驱动源码，集中存放设备连接、定位、规划和控制参数。

- `config.example.json`：SSH、部署路径、ROS 工作区及音视频设备配置示例。
- `amcl.yaml`：地图定位参数。
- `planner.yaml` / `motion.yaml`：全局规划与局部控制参数。
- `patrol_behaviors.yaml`：导航行为服务参数。
- `cyclonedds.xml`：本机 DDS 通信配置。
- `lio.template.yaml`：AidLux FAST-LIO 示例及雷达外参。
- `stairs_task_config.json`：可选楼梯任务配置。

在仓库根目录创建个人配置：

```bash
cp config/config.example.json config/config.local.json
```

`config.local.json` 不提交到 Git。所有路径由根目录的 `deployment.py` 统一解析，可通过 `D1_CONFIG` 指定其他个人配置文件。地图与点位仍放在 `maps/`。
