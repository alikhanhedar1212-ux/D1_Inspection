# D1_Inspection 的本机运行环境：Ubuntu 22.04 + ROS 2 Humble + Nav2
#
# 宿主机可以是 Ubuntu 24.04 / ROS 2 Jazzy（或其他发行版），所有 ROS 相关的
# 进程（导航、速度桥、语音巡检、BT 插件编译）都在本容器内运行；
# YOLO 训练、标注等留在宿主机 conda 环境，见 docker-run.sh 的说明。
#
# 构建：bash docker-run.sh --build
FROM osrf/ros:humble-desktop-full

RUN apt-get update && apt-get install -y \
    # Nav2 全家桶（amcl/planner/controller/bt_navigator 等）
    ros-humble-navigation2 \
    ros-humble-nav2-bringup \
    # 与 runtime_env.sh / patrol_config 匹配的中间件与插件
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-nav2-rotation-shim-controller \
    ros-humble-spatio-temporal-voxel-layer \
    # 图像与 TF
    ros-humble-cv-bridge \
    ros-humble-image-transport \
    ros-humble-tf2-ros \
    # BT 插件编译与运行语音/导航脚本的系统工具
    build-essential \
    cmake \
    git \
    openssh-client \
    python3-pip \
    python3-venv \
    # 电脑麦克风收音（pactl/parec/paplay 走宿主机 PulseAudio socket）
    pulseaudio-utils \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*
