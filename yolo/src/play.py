#!/usr/bin/env python3
"""
加载训练好的 YOLO 模型，对 RTSP 摄像头流或本地视频做实时目标检测。

视频来源可以是 RTSP 流（如 Unitree Go2 的相机），也可以是本地视频文件。
为降低延迟：缓冲区设为 1，且每次只处理内层循环读到的最新一帧（丢弃 2/3
的帧）。流中断时自动重连。按 q 退出窗口。

用法示例：
    python play.py                                    # 默认 RTSP 流 + 自动选权重
    python play.py --source video/sample.mp4          # 检测本地视频
    python play.py --model train_noflip            # 指定某次实验
    python play.py --model outputs/train_exp-3/weights/best.pt
"""

import argparse
import glob
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

WINDOW_TITLE = "YOLO on Go2"
DEFAULT_MODEL = os.path.join("outputs", "train_noflip", "weights", "best.pt")


def parse_args():
    parser = argparse.ArgumentParser(
        description="加载训练好的 YOLO 模型，对 RTSP 流或本地视频做实时检测。"
    )
    parser.add_argument(
        "--source", "-s",
        type=str,
        default=os.environ.get("D1_CAMERA_URL"),
        help="视频来源：RTSP 地址或本地视频文件路径，"
             "也可设置环境变量 D1_CAMERA_URL。",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="模型权重：best.pt 路径、实验目录或实验名（如 train_noflip）。"
             "不指定时默认用 outputs/train_noflip/weights/best.pt"
             "（fliplr=0 训练的 5 类模型），不存在则自动选 outputs 下最新的实验。",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.5,
        help="置信度阈值，默认 0.5。",
    )
    args = parser.parse_args()
    if not args.source:
        parser.error("请用 --source 指定视频地址，或设置 D1_CAMERA_URL")
    return args


def resolve_model_path(arg):
    """把 --model 参数解析成实际存在的权重文件路径。

    依次尝试：权重文件本身 -> 实验目录（补 weights/best.pt）-> outputs 下的
    实验名。未指定时先看默认路径，再退回 outputs 下最新的 best.pt。
    找不到任何权重时退出并报错。
    """
    if arg:
        candidates = [
            arg,
            os.path.join(arg, "weights", "best.pt"),
            os.path.join("outputs", arg, "weights", "best.pt"),
        ]
        for c in candidates:
            for base in (Path.cwd(), WORKSPACE):
                p = str((base / c).resolve())
                if os.path.isfile(p):
                    return p
        sys.exit(f"错误：找不到模型权重：{arg}\n"
                 f"可传 best.pt 路径、实验目录或实验名（如 train_exp-3）。")

    default_p = str(WORKSPACE / DEFAULT_MODEL)
    if os.path.isfile(default_p):
        return default_p

    bests = [os.path.abspath(p) for p in
             glob.glob(str(WORKSPACE / "outputs/*/weights/best.pt"))]
    if bests:
        newest = max(bests, key=os.path.getmtime)
        print(f"提示：默认权重 {DEFAULT_MODEL} 不存在，已自动改用最新的实验：{newest}")
        return newest

    sys.exit("错误：outputs 下找不到任何训练权重，请先运行 src/train.py 训练。")


def main():
    args = parse_args()

    # 用绝对路径加载模型，避免依赖启动目录
    model_path = resolve_model_path(args.model)
    print(f"加载模型：{model_path}")

    try:
        import cv2
    except ImportError:
        sys.exit("错误：需要安装 opencv-python，请运行 `pip install opencv-python`。")

    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("错误：需要安装 ultralytics，请运行 `pip install ultralytics`。")

    model = YOLO(model_path)
    print(f"检测类别：{model.names}")

    cap = cv2.VideoCapture(args.source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    while True:
        # 连续读 3 帧只保留最后一帧，降低显示延迟
        for _ in range(3):
            ret, frame = cap.read()
            if not ret:
                break
        if not ret:
            print("流中断，重连...")
            cap = cv2.VideoCapture(args.source)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            continue

        results = model(frame, conf=args.conf, verbose=False)
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                name = model.names[cls_id]
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                cv2.putText(frame, f'{name} {conf:.2f}', (int(x1), int(y1) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow(WINDOW_TITLE, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
