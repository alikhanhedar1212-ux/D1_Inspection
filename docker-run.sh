#!/usr/bin/env bash
# 在宿主机（如 Ubuntu 24.04 + ROS 2 Jazzy）上启动 D1_Inspection 的 Humble 容器。
#
# 用法：
#   bash docker-run.sh            # 镜像已存在则直接启动，否则先构建
#   bash docker-run.sh --build    # 强制重新构建镜像后启动
#
# 容器内开工前的准备（详见根目录 README.md 第 3~4 节）：
#   1. config/config.local.json 的 ros_setup 填 /opt/ros/humble/setup.bash
#   2. python3 -m venv --system-site-packages src/voice_navigation/.venv
#      src/voice_navigation/.venv/bin/python -m pip install -r requirements.txt scipy Pillow
#
# 说明：YOLO 训练/标注/抽帧不依赖 ROS，留在宿主机 conda 环境（go2_yolo）即可；
# 本容器只负责导航、速度桥、语音巡检和 BT 插件编译。
set -euo pipefail

IMAGE="d1:humble"
NAME="d1"
BUILD=0

for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --name)  shift; NAME="$1" ;;
        -h|--help)
            grep '^#' "$0" | head -20
            exit 0
            ;;
        *)
            echo "未知参数：$arg（支持 --build / --name）" >&2
            exit 1
            ;;
    esac
done

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$BUILD" -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "构建镜像 $IMAGE ..."
    docker build -t "$IMAGE" "$ROOT"
fi

# GUI（RViz）需要 X11 授权；Wayland 会话经 XWayland 同样生效
xhost +SI:localuser:root >/dev/null

# 麦克风/扬声器走宿主机 PulseAudio（Ubuntu 24.04 的 PipeWire 同样提供该 socket）
PULSE_UID="$(id -u)"

if [[ -z "${SSH_AUTH_SOCK:-}" ]]; then
    echo "警告：SSH_AUTH_SOCK 未设置，连接 firefly/aidlux 时无法使用 ssh-agent。" >&2
    echo "        请先执行 eval \$(ssh-agent) 并 ssh-add 你的私钥。" >&2
fi

echo "启动容器 $NAME（仓库挂载到容器内 /root/D1_Inspection）..."
# shellcheck disable=SC2086
docker run --rm -it \
    --name "$NAME" \
    --network=host \
    --env DISPLAY="$DISPLAY" \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -v "$HOME/.Xauthority:/root/.Xauthority:rw" \
    -v "/run/user/$PULSE_UID/pulse:/run/user/$PULSE_UID/pulse:rw" \
    --env "PULSE_SERVER=unix:/run/user/$PULSE_UID/pulse/native" \
    --device /dev/snd \
    -v "$HOME/.ssh:/root/.ssh:ro" \
    ${SSH_AUTH_SOCK:+-v "$SSH_AUTH_SOCK:/tmp/ssh_sock"} \
    ${SSH_AUTH_SOCK:+--env SSH_AUTH_SOCK=/tmp/ssh_sock} \
    -v "$ROOT:/root/D1_Inspection" \
    -w /root/D1_Inspection \
    "$IMAGE" bash
