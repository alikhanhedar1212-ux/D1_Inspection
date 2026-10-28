# 机器狗语音巡检与实时文字 UI

从正在使用的机器狗项目整理的源码快照，包含巡检、语音命令、导航集成和局域网实时转写页面。不是开箱即用的通用机器人软件；配置保留原设备路径、地图坐标和硬件接口。

## 当前行为

- 当前模式为 `navigation_test`：P1 → P2 → P3 → P4 → 本轮口令起点，各点停稳后等待 5 秒。
- P2 已同步至 2 号洗手间：x=-18.314848554370386，y=-4.714351507046586，yaw=1.6260092795020247 rad。第二站继续动态读取 `navigation_localization/waypoints.yaml` 中的 2 号点。
- 唤醒词为“小爱同学”；执行模式支持“开始巡检”和免唤醒“停止”。
- 完整视觉巡检适配器保留，但训练模型尚未接入；当前导航测试不代表视觉巡检已经验收。
- 转写 UI 默认监听 `0.0.0.0:8091`，同一局域网可访问。

## 目录

- `yolo/`：仓库已有视觉检测模块，保持原样；本次未将其接入巡检适配器。

- `voice_navigation/`：语音入口、巡检流程、配置、测试和网页。
- `navigation_localization/`：配套 ROS 2 导航、地图、RViz、传感器与速度桥源码。
- 根目录的 `camera_*.py`：摄像头传输依赖。
- `SOURCE_MANIFEST.json`：整理时复制文件的 SHA256，用于与原项目核对。

## 单独运行转写页面

```bash
python3 voice_navigation/voice_dashboard.py
```

本机访问 `http://127.0.0.1:8091/`；同一局域网设备访问 `http://电脑局域网IP:8091/`。页面读取同目录下监听程序实时生成的 `ui_events.jsonl`，单独启动页面不会启动识别。仅限本机时使用 `--host 127.0.0.1`。

## 实机运行前提

需要 Ubuntu/ROS 2 Humble、Nav2、对应机器人驱动和消息包。Python 依赖列于 `requirements.txt`，ROS 包需通过原设备环境安装。现有 `runtime_env.sh` 使用本地 Cyclone DDS 运行库；STVL 和自定义行为树插件也需要按原环境安装或构建。

源码保留 `/home/hcb/aidlux_mapping_view`、`/home/aidlux/...`、`/home/firefly/...` 等原部署路径。换电脑部署时需核对绝对路径、SSH 别名 `aidlux` / `firefly`、设备名及 ROS 域；也可将源码部署到原目录结构。不要直接覆盖正在运行的项目。

上传内容不包含 SSH 凭据、识别历史、运行日志、个人语音录音、Vosk 模型、训练权重、虚拟环境和 vendor 二进制库。实机语音还需要原环境中的 Vosk 中文模型、纽曼降噪配置 `newmine_noise_profile*.npz`、回复 WAV 和远端播放组件；这些资源需自行恢复。参考图仅供现有算法回归测试使用。

导航配置和地图来自当前现场，不能直接当成其他场地已校准的点位。启动顺序及硬件部署参考 `voice_navigation/PATROL.md`、`voice_navigation/README.md`，其中历史记录以最新配置为准。

## 离线检查

```bash
cd voice_navigation
python3 -m unittest test_patrol test_dashboard test_commands test_navigation_health
```

这些检查不触发实机运动，也不等于实走验收。
