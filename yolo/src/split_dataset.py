#!/usr/bin/env python3
"""
将数据集中的图片与标签按比例随机划分为 train/val/test 三个子集。

按文件名前缀（如 frame、turn_left、turn_right）分层分组，组内独立随机打乱
后再按比例切分，保证各来源在三个子集中的分布尽量均匀。无对应标签文件的
图片会作为背景样本随划分一起移动（YOLO 训练中自动视为背景）。

划分是"移动"而不是"复制"：执行后 images/train、labels/train 中只保留
train 子集的文件。若指定 --include，则只移动匹配前缀的文件，其余保持不动，
适合给新增的数据单独划分。labels 下的 classes.txt 会同步复制到各子目录
（labelImg 标注依赖该文件）。

用法示例：
    python split_dataset.py \
        --data datasets/my_dataset \
        --train 0.7 --val 0.1 --test 0.2 \
        --seed 42

    # 只把新标的两类按 8:2 划到 train/test（不碰其他数据）：
    python split_dataset.py --include turn_left go_straight --train 0.8 --val 0 --test 0.2
"""

import argparse
import os
import random
import shutil
import sys

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp")


def parse_args():
    parser = argparse.ArgumentParser(
        description="将 YOLO 数据集按比例随机划分为 train/val/test 三个子集。"
    )
    parser.add_argument(
        "--data", "-d",
        type=str,
        default="datasets/my_dataset",
        help="数据集目录（包含 images/train、labels/train），"
             "默认 datasets/my_dataset。",
    )
    parser.add_argument(
        "--train",
        type=float,
        default=0.7,
        help="训练集比例，默认 0.7。",
    )
    parser.add_argument(
        "--val",
        type=float,
        default=0.1,
        help="验证集比例，默认 0.1。",
    )
    parser.add_argument(
        "--test",
        type=float,
        default=0.2,
        help="测试集比例，默认 0.2。",
    )
    parser.add_argument(
        "--include", "-i",
        type=str,
        nargs="+",
        default=None,
        help="只划分这些文件名前缀的数据（如 --include turn_left go_straight），"
             "默认划分全部图片。",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子，默认 42，保证多次运行划分结果一致。",
    )
    return parser.parse_args()


def group_prefix(stem):
    """去掉末尾的编号段作为分层前缀，如 turn_round_000001 -> turn_round。"""
    return stem.rsplit("_", 1)[0]


def split_counts(n, ratio_train, ratio_val):
    """按比例计算 train/val/test 的数量，test 取余数保证三者之和等于 n。"""
    n_train = int(round(n * ratio_train))
    n_val = int(round(n * ratio_val))
    n_test = n - n_train - n_val
    return n_train, n_val, n_test


def main():
    args = parse_args()

    total_ratio = args.train + args.val + args.test
    if abs(total_ratio - 1.0) > 1e-6:
        sys.exit("错误：--train、--val、--test 三者之和必须等于 1。")
    if args.train <= 0 or args.val < 0 or args.test < 0:
        sys.exit("错误：比例必须满足 train > 0，val、test >= 0。")

    data_dir = args.data
    src_img_dir = os.path.join(data_dir, "images", "train")
    src_lab_dir = os.path.join(data_dir, "labels", "train")
    if not os.path.isdir(src_img_dir):
        sys.exit(f"错误：找不到图片目录：{src_img_dir}")

    images = [f for f in os.listdir(src_img_dir) if f.lower().endswith(IMG_EXTS)]
    if not images:
        sys.exit(f"错误：{src_img_dir} 中没有图片。")

    # 按前缀分层分组，组内独立打乱后切分
    groups = {}
    for f in images:
        groups.setdefault(group_prefix(os.path.splitext(f)[0]), []).append(f)

    # 若指定了 --include，只保留匹配前缀的组（用于单独划分某几类新数据）
    if args.include:
        include = set(args.include)
        matched = include & set(groups)
        if not matched:
            sys.exit(f"错误：--include 指定的前缀 {sorted(include)} 在数据集中不存在，"
                     f"现有前缀：{sorted(groups)}")
        groups = {p: fs for p, fs in groups.items() if p in include}

    rng = random.Random(args.seed)
    plan = {"train": [], "val": [], "test": []}  # 前缀 -> 文件名列表
    stats = {}
    for prefix, files in sorted(groups.items()):
        rng.shuffle(files)
        n_train, n_val, n_test = split_counts(len(files), args.train, args.val)
        plan["train"].extend(files[:n_train])
        plan["val"].extend(files[n_train:n_train + n_val])
        plan["test"].extend(files[n_train + n_val:])
        stats[prefix] = (len(files), n_train, n_val, n_test)

    for split in ("train", "val", "test"):
        os.makedirs(os.path.join(data_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "labels", split), exist_ok=True)

    # labelImg 依赖 labels 目录下的 classes.txt，划分时同步一份，避免新子集标注崩溃
    classes_src = os.path.join(src_lab_dir, "classes.txt")
    if os.path.isfile(classes_src):
        for split in ("train", "val", "test"):
            dst = os.path.join(data_dir, "labels", split, "classes.txt")
            if os.path.abspath(classes_src) != os.path.abspath(dst):
                shutil.copy(classes_src, dst)

    moved_imgs = {"train": 0, "val": 0, "test": 0}
    moved_labs = {"train": 0, "val": 0, "test": 0}
    missing_labs = 0
    for split in ("train", "val", "test"):
        for f in plan[split]:
            stem = os.path.splitext(f)[0]
            src_img = os.path.join(src_img_dir, f)
            dst_img = os.path.join(data_dir, "images", split, f)
            shutil.move(src_img, dst_img)
            moved_imgs[split] += 1

            src_lab = os.path.join(src_lab_dir, stem + ".txt")
            if os.path.isfile(src_lab):
                dst_lab = os.path.join(data_dir, "labels", split, stem + ".txt")
                shutil.move(src_lab, dst_lab)
                moved_labs[split] += 1
            else:
                missing_labs += 1

    print(f"数据集目录：{os.path.abspath(data_dir)}")
    print("\n各来源划分情况（前缀: 总数 -> train/val/test）：")
    for prefix, (n, n_train, n_val, n_test) in stats.items():
        print(f"  {prefix}: {n} -> {n_train}/{n_val}/{n_test}")
    print("\n各子集统计：")
    for split in ("train", "val", "test"):
        print(f"  {split}: 图片 {moved_imgs[split]} 张，标签 {moved_labs[split]} 个")
    print(f"\n无标注图片（作为背景样本）共 {missing_labs} 张。")
    print("完成：文件已移动到 images/{train,val,test} 与 labels/{train,val,test}。")


if __name__ == "__main__":
    main()
