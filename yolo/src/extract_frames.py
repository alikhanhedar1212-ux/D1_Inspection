#!/usr/bin/env python3
"""
从视频中截取指定时间段，并按指定帧率抽帧保存为图片。

用法示例：
    python extract_frames.py \
        --video /path/to/video.mp4 \
        --start 10 \
        --end 50 \
        --interval 0.2 \
        --output ~/d1_ws/yolo/datasets/my_dataset/images/train \
        --prefix frame
"""

import argparse
import os
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="截取视频指定时间段，并按固定时间间隔抽帧保存为图片。"
    )
    parser.add_argument(
        "--video", "-v",
        type=str,
        required=True,
        help="输入视频文件的路径。",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help="截取起始时间（秒），默认 0。",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="截取结束时间（秒）。若未指定，则到视频结尾。",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="抽帧时间间隔（秒），默认 0.2 秒/帧。",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        help="输出图片保存目录。",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="frame",
        help="输出图片文件名前缀，默认 'frame'。",
    )
    parser.add_argument(
        "--img-ext",
        type=str,
        default="jpg",
        choices=["jpg", "jpeg", "png", "bmp"],
        help="输出图片格式，默认 jpg。",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="输出文件名的起始编号，默认 0。",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=95,
        help="JPEG 保存质量（1-100），默认 95，仅对 jpg/jpeg 有效。",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="若图片文件已存在则覆盖，否则跳过。",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.interval <= 0:
        sys.exit("错误：--interval 必须大于 0。")
    if args.end is not None and args.end <= args.start:
        sys.exit("错误：--end 必须大于 --start。")

    try:
        import cv2
    except ImportError:
        sys.exit("错误：需要安装 opencv-python，请运行 `pip install opencv-python`。")

    if not os.path.isfile(args.video):
        sys.exit(f"错误：找不到视频文件：{args.video}")

    os.makedirs(args.output, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"错误：无法打开视频：{args.video}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    print(f"视频信息：fps={fps:.3f}, 总帧数={total_frames}, 时长={duration:.2f}s")

    end_time = args.end if args.end is not None else duration
    if args.start >= duration:
        sys.exit(f"错误：起始时间 {args.start}s 超出视频时长 {duration:.2f}s。")
    end_time = min(end_time, duration)

    # 计算每个采样点对应的时间（秒）
    sample_times = []
    t = args.start
    while t < end_time - 1e-9:
        sample_times.append(t)
        t += args.interval

    # 设置 JPEG 质量
    if args.img_ext in ("jpg", "jpeg"):
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), args.quality]
    else:
        encode_params = []

    saved = 0
    skipped = 0
    for i, t in enumerate(sample_times):
        # 用 seek 到对应帧（毫秒级精度）
        frame_idx = int(round(t * fps))
        if frame_idx >= total_frames:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            print(f"警告：读取 t={t:.3f}s (frame={frame_idx}) 失败，跳过。")
            continue

        filename = f"{args.prefix}_{args.start_index + i:06d}.{args.img_ext}"
        out_path = os.path.join(args.output, filename)

        if os.path.exists(out_path) and not args.overwrite:
            skipped += 1
            continue

        if not cv2.imwrite(out_path, frame, encode_params):
            print(f"警告：写入失败：{out_path}")
            continue
        saved += 1

        if saved % 50 == 0:
            print(f"已保存 {saved} 张，当前时间 {t:.3f}s ...")

    cap.release()
    print(f"完成：共保存 {saved} 张图片，跳过 {skipped} 张已存在的图片。")
    print(f"输出目录：{os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
