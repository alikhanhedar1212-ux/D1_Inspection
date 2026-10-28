# 驱动与配置

本目录放设备侧程序、摄像头传输、传感器输入和机器狗底层控制接口。

- `config/`：SSH/设备配置示例、ROS 参数、FAST-LIO 模板、DDS 配置。
- `start_remote_inputs.py`：在 AidLux 上启动雷达、输入转换和 FAST-LIO。
- `stream_sender.py` / `clock_probe.py`：传感器与时间同步传输。
- `camera_sender_latest.py`：AidLux 摄像头发送端；`camera_receiver.py` 在电脑接收。
- `velocity_receiver.py` / `receiver_guard.py`：Firefly 单实例速度接收端及超时保护。
- `posture_firefly.py` 与原生 C++ 源码：姿态、招手、电量等设备接口。

配置入口：

```bash
cp src/drivers/config/config.example.json src/drivers/config/config.local.json
```

默认从此配置读取 SSH、远端部署路径、ROS 工作区、音频设备和摄像头设备。导航用的 AMCL、规划器、控制器参数也集中在 `config/`；地图与点位在仓库的 `maps/`，页面与 RViz 配置在 `UI/`。

完整依赖与启动顺序见根目录 README。配置路径按项目位置解析，不依赖固定用户名。
