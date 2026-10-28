# AGENTS.md — YOLO 视觉检测工作区

面向 AI 编码代理的项目说明。本项目所有代码注释、CLI 帮助与文档均使用中文，修改代码时请保持一致。

## 项目概述

这是一个基于 Ultralytics YOLOv8 的视觉检测工作区，用于从视频/RTSP 摄像头流（推测来自 Unitree Go2 机器人，见 `src/d1_yolo.py`/`src/play.py` 窗口标题 "YOLO on Go2"）中做目标检测，并包含一套自制数据集的采集、划分与训练流程。本目录是 D1_Inspection 仓库的 `yolo/` 子目录（本地路径 `~/d1_ws/yolo/yolo`），仓库根目录还包含工程的其他部分。

项目不是可安装的 Python 包：没有 `pyproject.toml` / `setup.py`，也没有测试和 CI。代码以独立脚本形式组织，直接用 `python` 运行。依赖清单见 `requirements.txt`；工程已托管到 GitHub（远程 `origin` = https://github.com/alikhanhedar1212-ux/D1_Inspection）。

## 目录结构

```
yolo/
├── src/
│   ├── d1_yolo.py        # 实时检测脚本（旧）：COCO person 检测，需从 models/ 目录启动
│   ├── play.py           # 实时检测脚本：加载训练好的自定义权重，支持 RTSP/本地视频
│   ├── train.py          # 训练脚本：Ultralytics API 封装
│   ├── split_dataset.py  # 数据集划分脚本：按比例分层切分 train/val/test
│   └── extract_frames.py # 视频按固定时间间隔抽帧的 CLI 工具（数据采集中间步骤）
├── datasets/my_dataset/  # YOLO 格式自制数据集
│   ├── dataset.yaml      # 数据集配置（path / train / val / test / names）
│   ├── images/{train,val,test}/
│   └── labels/{train,val,test}/
├── models/yolov8n.pt     # YOLOv8n COCO 预训练权重（约 6.5 MB）
├── video/sample.mp4      # 样例视频：1920x1080 @ 30fps，约 50 秒，h264
├── logs/                 # 空目录，预留给训练日志
├── outputs/              # 训练输出目录（train.py 默认保存到 outputs/train_exp/）
└── requirements.txt      # Python 依赖清单（torch 需走 CUDA 源安装，见文件内注释）
```

## 技术栈与运行环境

- Python 3.10，conda 环境 `go2_yolo`（miniconda，解释器在 `~/miniconda3/envs/go2_yolo/bin/python3`）
- 关键依赖（pip 实际安装版本）：
  - `ultralytics` 8.4.176（含 `ultralytics-thop` 2.2.2）
  - `torch` 2.5.1+cu121 / `torchvision` 0.20.1+cu121（CUDA 12.1）
  - `opencv-python` 5.0.0.93、`numpy` 2.2.6
- 硬件：NVIDIA GeForce RTX 4060 Laptop GPU（训练/推理走 CUDA）

## 常用命令

### 训练（src/train.py）

```bash
python src/train.py                          # 默认参数：100 epochs、batch 16、YOLOv8n
python src/train.py --epochs 200 --batch 8   # 自定义轮数与批量
```

训练完成后最佳权重在 `outputs/<实验名>/weights/best.pt`。

注意：数据集含左右镜像的类别（turn_left/turn_right），`--fliplr` 默认 0（关闭水平翻转增强）——翻转会把左转样本变成右转的样子但标签不变，模型将分不清这两类。旧实验（train_exp ~ train_exp-4）都是在默认 fliplr=0.5 下训练的，存在该问题；排查类别混淆时先核对 `outputs/<实验名>/args.yaml` 里的 `fliplr`。

### 实时检测（src/play.py）

```bash
python src/play.py                                  # 默认 RTSP 流 + 自动选权重
python src/play.py --source video/sample.mp4        # 检测本地视频
python src/play.py --model train_exp-3              # 按实验名指定权重
python src/play.py --conf 0.5
```

加载自定义训练权重（5 类：turn_left/turn_right/turn_round/go_straight/extinguisher），视频来源可以是 RTSP 地址或本地视频文件。需要图形显示（`cv2.imshow`），按 `q` 退出。流中断时自动重连；内层循环每次丢弃 2/3 的帧以降低延迟。模型路径在脚本内转为绝对路径，可在工作区任意目录启动。

权重选择（`--model`）：支持 best.pt 路径、实验目录、实验名三种写法；不指定时默认 `outputs/train_noflip/weights/best.pt`（fliplr=0 的 5 类模型），不存在则自动选 outputs 下最新的实验。启动时会打印实际加载的权重路径和类别表。多次实验选优：对比各实验 `results.csv` 的 `metrics/mAP50(B)` / `metrics/mAP50-95(B)`；`yolo detect val data=datasets/my_dataset/dataset.yaml model=<权重> split=test` 可看分类别指标。注意 train_exp ~ train_exp-4 都是在 fliplr=0.5 下训练的，turn_left/turn_right 互相混淆，不要用。

### 数据集划分（src/split_dataset.py）

```bash
# 全量划分（默认 7:1:2）：
python src/split_dataset.py --train 0.7 --val 0.1 --test 0.2 --seed 42
# 只给新增的数据单独划分（不碰已有数据）：
python src/split_dataset.py --include turn_left go_straight --train 0.8 --val 0 --test 0.2
```

按文件名前缀分层分组后随机切分，**移动**（不是复制）图片与标签到 `images/{train,val,test}`、`labels/{train,val,test}`，并自动同步 `classes.txt` 到各 labels 子目录。`--include` 可指定只划分某些前缀（新增数据单独划分时用）。注意：不带 `--include` 重复运行前，需先把三个子集合并回 train，否则会报"没有图片"。

### 旧的实时检测脚本（src/d1_yolo.py）

```bash
cd ~/d1_ws/yolo/yolo/models && python ../src/d1_yolo.py
```

注意两点：
1. 脚本内模型路径是相对路径 `'yolov8n.pt'`，必须从 `models/` 目录启动（否则会尝试联网重新下载权重到当前目录）。
2. 脚本硬编码了 RTSP 地址 `rtsp://192.168.3.100:8554/test?tcp`，检测类别为 COCO 的 `classes=[0]`（person）。新代码请优先使用 `src/play.py`。

### 视频抽帧（src/extract_frames.py）

```bash
python src/extract_frames.py \
    --video video/sample.mp4 \
    --start 10 --end 50 --interval 0.2 \
    --output datasets/my_dataset/images/train \
    --prefix frame
```

按 `--interval`（秒）对 `--start` 到 `--end` 时间段抽帧，输出文件名为 `{prefix}_{编号:06d}.jpg`（编号可用 `--start-index` 续接，便于多段视频合入同一数据集而不重名）。已存在的文件默认跳过，`--overwrite` 覆盖。参数校验失败或缺少依赖时以中文错误信息退出（退出码非 0）。

## 数据集现状（datasets/my_dataset）

YOLO 格式（归一化 `class x_center y_center w h`），图片为 1920x1080 JPG。共 5 个类别，**类别号由文件名前缀决定**（标注时按前缀批量写死的，改类别名必须同步改前缀名/标签）：

| 类别号 | 类别名 | 文件名前缀 |
|---|---|---|
| 0 | turn_left | `turn_left_*` |
| 1 | turn_right | `turn_right_*` |
| 2 | turn_round | `turn_round_*`（原 turn_around） |
| 3 | go_straight | `go_straight_*` |
| 4 | extinguisher | `frame_*` |

当前规模（train 888 / val 70 / test 240）：

- `labels/train`：835 个 txt；`labels/val`：63 个；`labels/test`：223 个
- 77 张图片没有对应标注文件（YOLO 训练中这些会被当作背景样本）
- 2026-10-27 新增 go_straight、turn_left 各 250 张，已用 `split_dataset.py --include turn_left go_straight --train 0.8 --val 0 --test 0.2` 按 8:2 划入 train/test
- 每个 labels 子目录下都有 `classes.txt`（5 个类别名，顺序与上表一致）：labelImg 的 YOLO 模式靠它读类别名，缺少会崩溃；Ultralytics 训练会忽略该文件，类别号以 `dataset.yaml` 的 `names` 为准。`split_dataset.py` 划分时会自动同步该文件
- ⚠️ labelImg 保存时会按它记录的类别表重写 classes.txt，标注后若发现该文件被改动需立即恢复，否则 id↔名称映射会错乱

`dataset.yaml` 中 `path` 为绝对路径 `/home/ubuntu20/d1_ws/yolo/yolo/datasets/my_dataset`，迁移工作区后需同步修改。

注意：Git 仓库不包含数据集图片（`datasets/my_dataset/images/`）和 `video/`（太大，见根目录 `.gitignore`），labels 和 dataset.yaml 正常入库；图片/视频通过网盘或 GitHub Release 另行分享。

## 代码风格约定

- 所有注释、docstring、CLI `--help`、错误提示均使用**简体中文**（如“流中断，重连...”、“错误：--interval 必须大于 0。”），新代码请沿用。
- 脚本式入口：`if __name__ == "__main__": main()`，参数用 `argparse` 定义，短选项 + 长选项并存（如 `--video` / `-v`）。
- 致命错误用 `sys.exit("错误信息")` 结束，不做复杂的异常包装。
- `cv2`、`ultralytics` 等重依赖放在函数内导入并给出中文安装提示，因为这些依赖在运行期才需要。

## 测试与部署

- 项目没有任何自动化测试；验证方式是手动运行脚本并观察输出（抽帧脚本会打印视频信息、保存进度和完成统计，划分脚本会打印各子集统计）。
- 无构建步骤、无 CI/CD、无容器/部署配置。`logs/` 是预留占位目录；`outputs/` 存放训练产物。
