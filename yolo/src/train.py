#!/usr/bin/env python3
"""
使用 Ultralytics YOLOv8 在自制数据集上训练目标检测模型。

训练完成后，最佳权重保存在 outputs/train_exp/weights/best.pt，
可用 src/play.py 加载该权重做实时检测。

用法示例：
    python train.py                                # 使用默认参数训练
    python train.py --epochs 200 --batch 8         # 自定义轮数与批量
    python train.py --data datasets/my_dataset/dataset.yaml
"""

import argparse
import os
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(
        description="在自制数据集上训练 YOLOv8 检测模型。"
    )
    parser.add_argument(
        "--data", "-d",
        type=str,
        default=str(WORKSPACE / "datasets/my_dataset/dataset.yaml"),
        help="数据集配置 yaml 路径，默认 datasets/my_dataset/dataset.yaml。",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=str(WORKSPACE / "models/yolov8n.pt"),
        help="初始权重路径，默认 models/yolov8n.pt（YOLOv8n COCO 预训练权重）。",
    )
    parser.add_argument(
        "--epochs", "-e",
        type=int,
        default=100,
        help="训练轮数，默认 100。",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="输入图片尺寸，默认 640。",
    )
    parser.add_argument(
        "--batch", "-b",
        type=int,
        default=16,
        help="批大小，默认 16；显存不足时可调小。",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="0",
        help="训练设备，默认 '0'（第一块 GPU）；CPU 训练填 'cpu'。",
    )
    parser.add_argument(
        "--fliplr",
        type=float,
        default=0.0,
        help="训练时水平翻转增强的概率，默认 0。本数据集含左右镜像的类别"
             "（turn_left/turn_right），水平翻转会制造标签噪声，切勿调大。",
    )
    parser.add_argument(
        "--project", "-p",
        type=str,
        default=str(WORKSPACE / "outputs"),
        help="训练输出根目录，默认 outputs。",
    )
    parser.add_argument(
        "--name", "-n",
        type=str,
        default="train_exp",
        help="本次训练的名称，默认 train_exp。",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.isfile(args.data):
        sys.exit(f"错误：找不到数据集配置：{args.data}")
    if not os.path.isfile(args.model):
        sys.exit(f"错误：找不到模型权重：{args.model}")

    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("错误：需要安装 ultralytics，请运行 `pip install ultralytics`。")

    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        # 传绝对路径，避免旧版 Ultralytics 把相对 project 套进 runs/detect 下
        project=os.path.abspath(args.project),
        name=args.name,
        # 左右镜像类（turn_left/turn_right）存在时水平翻转会制造标签噪声
        fliplr=args.fliplr,
    )

    best = os.path.join(args.project, args.name, "weights", "best.pt")
    print(f"训练完成，最佳权重：{best}")
    print(f"实时检测：python src/play.py --model {best}")


if __name__ == "__main__":
    main()
