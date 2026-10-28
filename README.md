# 机器狗语音巡检与实时文字 UI

代码按所在目录自动定位资源，可克隆到任意目录，无需修改源码中的用户名或本机路径。远端 SSH、部署目录和音频设备统一配置在 `config.local.json`。

## 当前功能

- 语音唤醒“小爱同学”，支持“开始巡检”和免唤醒“停止”。
- 当前为 `navigation_test`：P1 → P2 → P3 → P4 → 本轮口令起点，各点停稳后等待 5 秒。
- P2 已与 2 号洗手间的位置和方向同步，第二站继续动态读取 `navigation_localization/waypoints.yaml` 的 2 号点。
- 网页显示实时转写和巡检状态，默认监听所有 IPv4 网卡的 8091 端口。
- 完整视觉巡检适配器保留，仓库已有 `yolo/` 模块尚未与巡检适配器集成。当前导航测试不代表视觉巡检验收。

## 先运行网页

只需 Python 3，无需 ROS 或模型。在仓库根目录执行：

```bash
python3 doctor.py
python3 voice_navigation/voice_dashboard.py
```

电脑访问 `http://127.0.0.1:8091/`，局域网设备访问 `http://电脑局域网IP:8091/`。网页读取识别进程生成的 `voice_navigation/ui_events.jsonl`，不会自行启动麦克风或发送运动命令。只允许本机访问可加 `--host 127.0.0.1`。

## 配置设备

```bash
cp config.example.json config.local.json
```

在电脑、AidLux 和 Firefly 上部署同一份源码。远端默认目录为各自登录用户的 `~/D1_Inspection`；如果改了目录名或放到其他位置，在电脑的配置中修改 `aidlux_root` / `firefly_root`。路径可以包含空格，`~` 在远端展开。远端设备自己的配置也需设置本机所用 ROS 环境和音频设备。

- `aidlux_host` / `firefly_host`：SSH 别名或 `用户名@地址`，通过 `~/.ssh/config` 设置端口、跳板及密钥。使用密钥认证，并先手动连接以确认主机指纹。
- `aidlux_root` / `firefly_root`：远端仓库根目录。
- `ros_setup`：ROS setup 文件，本机和远端都可配置。仅当前终端覆盖可用 `D1_ROS_SETUP`。
- `aidlux_workspace_setup`：AidLux 雷达和 FAST-LIO 驱动工作区的 `install/setup.bash`；驱动已经在系统环境中时可留空。
- `firefly_workspace_setup`：Firefly 厂商驱动 setup 文件。
- `microphone` / `speaker`：PulseAudio 设备名，分别用 `pactl list short sources` / `pactl list short sinks` 查询。本机收音可用 `--source` 明确指定输入。
- `mapping_config`：AidLux 的 FAST-LIO 模板，默认相对于其仓库根目录的 `navigation_localization/lio.template.yaml`。示例保留原设备雷达外参，换设备需要校准。
- 远端 ROS 域默认 AidLux 为 0、Firefly 为 24；本机导航域为 93。

已有设备目录结构不同，也可设置 `aidlux_navigation_localization_dir`、`aidlux_voice_navigation_dir`、`firefly_navigation_localization_dir`、`firefly_voice_navigation_dir`，分别覆盖远端模块目录。

`config.local.json` 已被 Git 忽略。可用 `D1_CONFIG` 指定其他 JSON 配置文件；该环境变量只对设置它的机器生效，不会自动复制到远端。

## 安装本机依赖

需要 Ubuntu、Python 3.10+、ROS 2 Humble、Nav2、Cyclone DDS、RotationShimController、STVL，以及 PulseAudio 命令行工具。厂商驱动和对应 ROS 消息需在设备上安装。支持系统安装的 DDS/STVL，也兼容放在 `navigation_localization/vendor/` 下的原有运行库；vendor 二进制不入库。

```bash
python3 -m venv --system-site-packages voice_navigation/.venv
voice_navigation/.venv/bin/python -m pip install -r requirements.txt
source navigation_localization/runtime_env.sh
cmake -S navigation_localization/terminal_replan -B navigation_localization/terminal_replan/build
cmake --build navigation_localization/terminal_replan/build -j2
```

在远端也需安装其脚本所用依赖。AidLux 摄像头需要 OpenCV，播放需要 `paplay`，录音需要 `parec` 和 `ffmpeg`。Firefly 速度接收端需要厂商消息包和 Zenoh ROS 中间件。

### 单独准备资源

仓库不包含个人语音录音、语音模型、降噪数据和厂商二进制。部署前需要自行准备：

- Vosk 中文模型解压至 `voice_navigation/models/vosk-model-small-cn-0.22/`。
- 纽曼麦克风校准文件 `voice_navigation/newmine_noise_profile.npz`；远端收音使用 `newmine_noise_profile_remote.npz`。这些文件是校准数据，不能用空文件替代。
- 回复 WAV 放入本机及 AidLux 的 `voice_navigation/audio/`，包含 `wake_reply.wav`、`okay.wav` 和巡检的 `device_normal.wav`、`device_missing.wav`、`camera_error.wav`、`planning_error.wav`、`sign_error.wav`。其他可选语音功能所需文件见模块说明。
- 电量查询和打招呼为可选功能，需要在 Firefly 用对应架构的 eCAL/厂商 SDK 编译 `read_battery_native.cpp`、`greet_native.cpp`，将可执行文件放到其 `voice_navigation/` 下。

```bash
source navigation_localization/runtime_env.sh
voice_navigation/.venv/bin/python doctor.py --robot
```

检查只报告本机缺失项，不连接或驱动机器人。它不代替远端驱动、ROS 插件或现场地图校准验收。

## 启动导航与语音

1. 在 AidLux 的仓库内执行，启动传感器输入：

   ```bash
   python3 navigation_localization/start_remote_inputs.py
   ```

2. 在电脑的仓库内执行，打开定位、规划、摄像头和 RViz：

   ```bash
   python3 navigation_localization/restore_planning_only.py
   ```

3. 核对现场地图、机身朝向和点位后，在电脑另开终端连接速度桥：

   ```bash
   source navigation_localization/runtime_env.sh
   python3 navigation_localization/velocity_bridge.py
   ```

4. 在电脑启动语音，首次可先不加 `--execute` 验证识别；需要实机执行时使用：

   ```bash
   bash voice_navigation/run_computer_mic.sh --execute
   ```

5. 用前文的命令启动网页查看转写。

启动器按脚本位置解析路径，可从任意工作目录调用；上面使用相对命令便于在仓库根目录复制执行。`run.sh` 优先使用同目录虚拟环境，否则使用当前环境的 `python3`，也可通过 `D1_PYTHON` 指定解释器。

地图与点位属于原现场。更换场地需要更新地图、定位参数和 P1～P4，不可直接把原坐标视为新场地已校准。可选楼梯交接后端不在本巡检仓库中，其旧工具会明确提示缺失。

## 源码与验证

- `voice_navigation/`：语音、巡检流程、网页、配置和测试。
- `navigation_localization/`：配套地图、定位、规划、RViz 和速度桥。
- `camera_*.py`：摄像头传输。
- `yolo/`：已有视觉检测及训练模块，视频源通过 `--source` 或 `D1_CAMERA_URL` 指定，未自动接入巡检。
- `deployment.py`：集中配置、远端路径及 SSH 命令构造。
- `SOURCE_MANIFEST.json`：所列源码文件的 SHA256；后续修改源码后需更新。

```bash
voice_navigation/.venv/bin/python -m unittest test_deployment -v
voice_navigation/.venv/bin/python -m unittest discover -s voice_navigation -q
```

迁移测试覆盖重命名目录、含空格路径、远端 home 展开与参数转义。可选楼梯几何测试在未提供楼梯地图时跳过。这些离线检查不触发实机运动。
