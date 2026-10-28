# D1_Inspection：共用机器狗的语音巡检

本项目用于让电脑连接实验室共用的 **AidLux 和 Firefly**，实现语音下达任务、地图定位、路径规划和巡检，并在网页显示实时识别文字。

**本文面向更换电脑的使用者。AidLux、Firefly、机器人驱动和地图由设备维护者统一维护，使用者不需要在每次接入时重新部署设备端。** 以下命令均从克隆后的仓库根目录执行，不依赖电脑用户名或固定的 `/home/...` 路径。

## 先了解目前能运行什么

当前配置 `maps/patrol_config.json` 的 `mode` 为 `navigation_test`，支持：

1. 唤醒“小爱同学”，听到“我在”后说“开始巡检”。
2. 按 P1 → P2 → P3 → P4 的顺序导航，各点停稳后等待 5 秒。
3. 返回收到“开始巡检”口令时机器狗的位置及朝向，结束任务。
4. 随时说“停止”取消任务，无须唤醒。

P2 当前与普通 2 号洗手间点相同；第二站仍通过 `stop_overrides` 动态读取 `maps/waypoints.yaml` 的 2 号点。

**上述流程是导航巡检。灭火器检测、路标识别等完整视觉巡检还需要接入模型适配器。** 仓库虽然包含 `yolo/`，但它尚未与巡检状态机连接，不能仅因存在 YOLO 权重就认为完整视觉巡检已经可用。视觉接入要求见本文最后一节。

## 1. 接入前向设备维护者领取资料

新电脑需要准备以下内容：

- 共用设备所连接的网络，以及当前 Firefly、AidLux 的 SSH 地址、账号、端口和跳板方式。
- 自己的 SSH 公钥在设备上的登录授权。不要复制其他人的 SSH 私钥。
- **与共享设备当前脚本版本和目录相匹配的 `config.local.json`。** 文件放在本机 `config/` 下。
- 本机运行所需的资源包：Vosk 中文模型、麦克风降噪校准数据和回复录音。
- 确认本机仓库版本与设备端接口兼容；领取当前现场地图和点位的最新版本。

默认远端路径是各设备登录用户的 `~/D1_Inspection/src/...`，它只是默认值，**并不是对现有共享设备部署位置的确认**。设备可能仍使用 `navigation_preview`、`mapping_test`、`rviz_navigation` 等既有目录。

如果设备端采用旧目录结构，应先由维护者确认路径和版本兼容性，再提供可用配置。`aidlux_drivers_dir` 等覆盖项只能覆盖一个模块目录；如果摄像头与传感器脚本分别散落在多个旧目录，仅修改一个目录值并不足够，需维护者完成一次接口或目录适配。普通使用者不要为了匹配示例路径重装、移动或覆盖共享设备程序。

同一时间由一台电脑运行语音执行程序和速度桥。更换控制电脑前，先让上一位使用者停止任务并退出控制进程。

## 2. 在新电脑克隆项目

建议使用带图形桌面的 Ubuntu 22.04、Python 3.10 和 ROS 2 Humble。RViz 需要可用的桌面显示环境。

```bash
git clone https://github.com/alikhanhedar1212-ux/D1_Inspection.git
cd D1_Inspection
```

可以克隆到自己的任意目录，也可以重命名仓库文件夹。后续每个新终端先进入自己的仓库根目录。

```text
D1_Inspection/
├── src/
│   ├── drivers/                  # 设备侧接口、传感器和摄像头传输
│   ├── navigation_localization/  # 本机定位、规划、速度桥和启动器
│   └── voice_navigation/         # 语音识别与巡检流程
├── config/                       # 连接配置、ROS 参数和 DDS 配置
├── maps/                         # 地图、六个语音点和巡检点位
├── UI/                           # 网页、HTTP 服务和 RViz 显示配置
├── tests/                        # 路径迁移与配置测试
├── yolo/                         # 已有视觉检测模块，尚未接入巡检
├── deployment.py                 # 公共配置与路径解析
├── doctor.py                     # 本机依赖和资源检查
└── requirements.txt
```

## 3. 安装电脑端环境

### ROS 与系统组件

在新电脑安装 ROS 2 Humble，并准备下列组件；如果没有安装经验，可请维护者提供已经验证的环境或安装方式：

- Nav2：地图服务、AMCL、规划器、控制器、行为树、生命周期管理和 RViz 导航面板。
- `rmw_cyclonedds_cpp`：本机导航使用 Cyclone DDS。
- `nav2_rotation_shim_controller`：转向控制插件。
- `spatio_temporal_voxel_layer`：动态障碍物体素层。
- ROS 图像消息与 `cv_bridge`、TF 和相关 Nav2 消息包。
- `git`、OpenSSH 客户端、CMake、C++ 编译器。
- PulseAudio 命令：`pactl`、`parec`、`paplay`。

`requirements.txt` 仅安装 Python 第三方库，不安装 ROS、厂商 SDK、模型或录音。本机不需要重新安装设备上的雷达驱动和厂商运动控制服务。

### Python 环境

使用系统 Python 创建虚拟环境，让它能读取系统安装的 ROS Python 包：

```bash
python3 -m venv --system-site-packages src/voice_navigation/.venv
src/voice_navigation/.venv/bin/python -m pip install -r requirements.txt
src/voice_navigation/.venv/bin/python -m pip install scipy Pillow
```

导航辅助脚本和摄像头接收端由系统 `python3` 启动，因此系统环境也需要能导入 `numpy`、`yaml`、`cv2`、`scipy` 和 `PIL`，以及 ROS 的 `rclpy`、`cv_bridge`。可通过发行版的 Python 包安装这些库；仅装进语音虚拟环境不足以满足所有启动器。

### 构建本机行为树插件

先完成第 4 节的个人配置，再执行：

```bash
source src/navigation_localization/runtime_env.sh
cmake -S src/navigation_localization/terminal_replan -B src/navigation_localization/terminal_replan/build
cmake --build src/navigation_localization/terminal_replan/build -j2
```

预期生成 `src/navigation_localization/terminal_replan/build/libterminal_replan_bt_node.so`。

若提示缺少 `librmw_cyclonedds_cpp.so`、STVL 或 RotationShim 插件，应补齐本机对应 ROS 依赖。不要把源码仓库中未提供的 `vendor/` 二进制库当成已经安装；也不要为了跳过依赖错误直接更换现有导航中间件配置。

## 4. 配置新电脑连接共用设备

### 配置 SSH

把自己的公钥交给维护者授权后，在电脑的 `~/.ssh/config` 中设置连接信息。下面是结构示例，尖括号内容必须替换为维护者提供的实际值：

```sshconfig
Host firefly
    HostName <Firefly当前可达IP>
    User <Firefly登录用户>
    Port 22
    IdentityFile ~/.ssh/<本机用于Firefly的私钥>

Host aidlux
    HostName <AidLux当前IP>
    User <AidLux登录用户>
    Port 22
    IdentityFile ~/.ssh/<本机用于AidLux的私钥>
    ProxyJump firefly
```

如果本机可直接访问 AidLux，不需要跳板，可按维护者要求移除 `ProxyJump`。用户名、密钥文件名和端口都不要求与其他电脑相同。

在终端手动连接一次，核对主机指纹并完成登录，再退出：

```bash
ssh firefly
ssh aidlux
```

自动化脚本使用 `BatchMode=yes`，因此后续连接不能依赖交互输入登录密码。加密私钥可以通过本机 SSH agent 解锁。

### 配置项目

优先使用维护者提供的、匹配共用设备的个人配置；没有现成配置时，以示例创建：

```bash
cp config/config.example.json config/config.local.json
```

核对以下字段：

- `aidlux_host` / `firefly_host`：本机 SSH 别名，通常为 `aidlux`、`firefly`。
- `aidlux_root` / `firefly_root`：设备上的仓库根目录，**不是新电脑的克隆路径**。仅当设备采用完整仓库结构时使用此默认推导。
- `aidlux_drivers_dir` / `firefly_drivers_dir`：可选的设备侧驱动模块目录覆盖。
- `aidlux_voice_navigation_dir` / `firefly_voice_navigation_dir`：可选的设备侧语音模块目录覆盖。
- `ros_setup`：本机及远端默认 ROS setup 路径；也支持 `aidlux_ros_setup`、`firefly_ros_setup` 分别覆盖。当前终端的本机 setup 可用 `D1_ROS_SETUP` 覆盖。
- `aidlux_workspace_setup` / `firefly_workspace_setup`：设备已有驱动工作区的 setup 文件，由维护者提供。
- `speaker`：AidLux 上共用回复扬声器的 PulseAudio 名称。
- `microphone`：使用 AidLux 收音时的输入名称。默认电脑收音模式见第 6 节。
- `aidlux_domain` / `firefly_domain`：默认分别为 0、24，应与设备现有 ROS 域一致；本机导航域固定为 93。
- `camera_device` / `mapping_config`：设备侧配置项，通常保留共享设备既有值，普通使用者不需要重新校准或覆盖它们。

本机资源路径会根据项目位置自动定位，不需要写自己的 `/home/用户名/项目名`。`~` 开头的远端路径在远端展开。

`config/config.local.json` 不上传 Git。可通过 `D1_CONFIG` 使用其他个人配置文件；本机环境变量不会自动传到设备，设备侧继续使用维护者配置好的环境。

## 5. 放置资源包

这些文件没有随源码上传，需要从维护者领取或按已有部署流程准备，不能用空文件代替：

```text
src/voice_navigation/
├── models/
│   └── vosk-model-small-cn-0.22/   # 解压后的完整中文识别模型
├── newmine_noise_profile.npz      # 电脑纽曼麦克风降噪校准数据
└── audio/
    ├── wake_reply.wav             # 我在
    ├── okay.wav                   # 好的
    ├── device_normal.wav
    ├── device_missing.wav
    ├── camera_error.wav
    ├── planning_error.wav
    └── sign_error.wav
```

电脑离线识别必须有本机 Vosk 模型。当前纽曼麦克风模式会检查降噪配置；换麦克风或增益后，应核对校准数据是否仍适用。

电脑收音、机器狗播报时，实际回复由 AidLux 播放其已有 WAV。领取本机资源包不等于把 AidLux 上的录音重新部署了一遍，维护者需要确认设备端缓存已经可用。其他可选语音功能还可能需要定位、打招呼、开门提示等额外 WAV；单纯完成当前导航巡检不要求重新编译电量查询或打招呼程序。

地图和点位使用同一套共享现场的已确认版本。普通使用者不要修改原点、雷达外参、P1～P4 或将 `confirmed` 改为 `true` 来绕过检查。

## 6. 检查环境与麦克风

连接电脑使用的 USB 麦克风，查询输入设备：

```bash
pactl list short sources
```

电脑收音模式默认选择唯一的 Newmine 麦克风，不会悄悄退回内置麦克风。设备名称不同或有多个候选时，启动语音脚本时使用 `--source` 指定列表中的实际名称。

执行本机检查：

```bash
source src/navigation_localization/runtime_env.sh
src/voice_navigation/.venv/bin/python doctor.py --robot
```

处理所有与本次功能有关的 `MISSING` 项。此工具只检查部分本机文件、Python 模块和命令；它不会连接机器人，也不会完整验证所有 ROS 动态库、设备端脚本或现场定位。

如需先检查代码和目录引用，可执行以下离线测试，不触发机器人运动：

```bash
src/voice_navigation/.venv/bin/python -m unittest discover -s tests -v
src/voice_navigation/.venv/bin/python -m unittest discover -s src/voice_navigation -q
python3 -m unittest discover -s UI -v
```

可选楼梯几何测试在未提供楼梯地图时会跳过，不影响当前导航巡检。

## 7. 按顺序启动巡检

下面的终端均位于**新电脑的仓库根目录**。每个新终端独立加载需要的环境，保持进程运行。

### 第一步：确认共用设备已就绪

向维护者确认设备已开机、网络可达，底层控制、雷达、FAST-LIO 和输入转换已正常工作，且上一台电脑已退出控制。

设备侧传感器输入只需要一套。若尚未启动，由维护者使用现有设备启动入口启动；不要在新电脑本地运行 `src/drivers/start_remote_inputs.py`，它是 AidLux 程序，也不要在设备上重复启动同一套输入。

### 第二步：终端 A，启动定位、规划、摄像头与 RViz

```bash
python3 src/navigation_localization/restore_planning_only.py
```

此入口启动本机导航相关进程并打开 `UI/rviz/navigation_drive.rviz`，但不启动硬件速度桥。等待实时雷达、图像和地图显示，确认机器人位置及机身方向与实物一致。

另外打开一个检查终端，核对导航节点：

```bash
source src/navigation_localization/runtime_env.sh
ros2 lifecycle get /amcl
ros2 lifecycle get /planner_server
ros2 lifecycle get /controller_server
ros2 lifecycle get /bt_navigator
```

应返回 `active [3]`。只有窗口出现、页面在线或动作服务存在，并不代表导航节点已经可用。

### 第三步：终端 B，连接速度桥

确认定位、设备状态和通道条件后，在本机执行：

```bash
source src/navigation_localization/runtime_env.sh
python3 src/navigation_localization/velocity_bridge.py
```

底层模式是否允许导航速度仍由 Firefly 接收端和机器人现有反馈决定。不要同时在另一台电脑运行第二套速度桥。

### 第四步：终端 C，启动语音

首次接入可先检查识别和回复，不发运动目标：

```bash
bash src/voice_navigation/run_computer_mic.sh
```

说“小爱同学”，确认机器狗回答“我在”。测试完成后在此终端按 `Ctrl+C` 退出，再启动执行模式：

```bash
bash src/voice_navigation/run_computer_mic.sh --execute
```

指定其他输入设备时，使用实际名称，例如：

```bash
bash src/voice_navigation/run_computer_mic.sh --execute --source '<pactl输出的完整麦克风名称>'
```

`run.sh` 优先使用 `src/voice_navigation/.venv/bin/python`，否则使用当前环境的 `python3`；需要自定义解释器时可设置 `D1_PYTHON`。

### 第五步：终端 D，打开实时文字 UI

```bash
python3 UI/voice_dashboard.py
```

本机访问 `http://127.0.0.1:8091/`；同一局域网的手机或其他电脑访问 `http://运行服务的电脑IP:8091/`。只允许本机访问时添加 `--host 127.0.0.1`。

页面读取 `src/voice_navigation/ui_events.jsonl` 和监听状态。只开页面不会启动麦克风、语音识别或导航，也不能代替上述启动步骤。

### 第六步：下达巡检任务

1. 说“小爱同学”，等待“我在”。
2. 说“开始巡检”。
3. 在 UI 中观察任务阶段，在 RViz 中观察定位与路径。
4. 等待 P1～P4 导航、各点停留和返回本轮起点完成。

当前指令窗口为 30 秒，有效指令会续期；超时后需要重新唤醒。“停止”无须唤醒。

## 8. 停止任务与更换电脑

先说“停止”，或在加载本机导航环境后调用：

```bash
source src/navigation_localization/runtime_env.sh
ros2 service call /stop_navigation std_srvs/srv/Trigger '{}'
```

确认任务取消、速度为零后，先退出语音执行程序，再退出速度桥。网页服务可以在自己的终端用 `Ctrl+C` 结束。

`restore_planning_only.py` 会把子进程放到独立会话；启动器退出不代表这些进程已经全部停止，进程记录位于 `src/navigation_localization/restored_processes.json`。结束会话时由当前操作者或维护者核对并清理，确认控制权已释放后再交给下一台电脑。

仓库中的 `shutdown_navigation_session.py` 还会尝试停止设备侧相关输入。对于共用设备，不应把它当成只退出个人电脑进程的按钮；整套系统关停由维护者协调。

## 9. 常见接入问题

- **SSH 超时或要求密码**：检查网络、跳板、账号、公钥授权和 SSH agent；先保证两台设备都可从新电脑免交互登录。
- **远端提示脚本不存在**：设备布局与默认 `~/D1_Inspection/src/...` 不一致。领取维护者确认的配置与兼容脚本，不要在电脑配置中填写电脑自己的项目路径来代替设备路径。
- **缺少 Cyclone DDS、STVL 或 RotationShim 库**：补齐本机 ROS 插件。语音虚拟环境安装成功不等于 ROS 动态库已安装。
- **没有实时雷达或图像**：检查设备侧输入状态、SSH 及目录匹配，再查看本机 `src/navigation_localization/runtime_logs/`。
- **页面有文字但机器狗不走**：检查是否使用 `--execute`、速度桥是否运行、Nav2 是否 active、定位是否合格，以及底层模式反馈；页面在线不代表运动条件满足。
- **提示麦克风或降噪数据缺失**：检查 Newmine 是否唯一、`--source` 是否正确，以及校准文件是否位于要求目录。
- **提示监听已运行**：先退出自己的旧监听进程，不能重复启动两套语音程序。
- **提示视觉模型未接入**：当前完整视觉巡检的适配器仍未配置；不要把模型缺失解释成“设备丢失”。

## 10. 后续实现完整视觉巡检还需要什么

这部分由项目维护者统一接入，普通使用者完成前面的电脑接入流程后，先使用 `navigation_test`。

维护者需要完成：

1. 确定使用的训练权重、类别表、推理设备和依赖，将 `yolo/` 的输出适配到巡检接口。
2. 编写可导入的 Python 模块，并在 `maps/patrol_config.json` 的 `vision.module` 中指定模块名；模块须对语音执行进程可导入。
3. 模块提供 `create_detector(settings)`，返回具备 `ready()` 和 `detect(frame, kind)` 的对象。
4. `frame` 是新鲜摄像头 BGR 图像；`kind` 为 `extinguisher` 或 `sign`。检测返回 `(label, evidence_dict)`。
5. 将模型类别映射为 `extinguisher`、`forward`、`left`、`right`、`uturn`。成功推理但未检出可返回 `None`，推理错误必须抛异常。
6. 完成现场图像、连续帧确认、异常播报、路标返回路线与任务取消验证后，再协调切换至视觉巡检模式。

接口实现见 `src/voice_navigation/patrol_detection.py`，任务流程见 `src/voice_navigation/patrol_runtime.py`。只修改 `mode` 或填写一个权重路径，不能替代模型适配与验证。
