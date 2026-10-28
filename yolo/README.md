> 迁移说明：视频源请通过 --source 或环境变量 D1_CAMERA_URL 指定，不再默认连接原设备 IP。模型默认路径按脚本位置解析，数据集根目录按 dataset.yaml 所在目录解析。下面出现的 RTSP 地址仅为原设备示例。

# YOLO 视觉检测工作区

基于 Ultralytics YOLOv8 的目标检测工作区：从 RTSP 摄像头流（Unitree Go2）采集视频 → 抽帧制作数据集 → 训练自定义模型 → 实时检测。共 5 个类别：**turn_left（0）、turn_right（1）、turn_round（2）、go_straight（3）、extinguisher（4）**，类别号与图片文件名前缀一一对应。

本目录是 D1_Inspection 仓库的 `yolo/` 子目录（本地路径 `~/d1_ws/yolo/yolo`），仓库根目录还包含工程的其他部分。以下命令均在本目录（即 `yolo/` 子文件夹）下运行。

## 环境准备

```bash
conda activate go2_yolo
pip install -r requirements.txt
# torch/torchvision（CUDA 12.1）需走官方源：
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
```

## 1. 录制 RTSP 视频（ffmpeg）

用 ffmpeg 从 Go2 相机录一段 50 秒的原始流，保存为本地视频（`-c copy` 不转码，画质无损、CPU 占用低，适合采集训练数据）：

```bash
ffmpeg -rtsp_transport tcp -i rtsp://192.168.3.100:8554/test -t 50 -c copy video/sample.mp4
```

参数说明：`-rtsp_transport tcp` 强制 TCP 传输更稳定；`-t 50` 录制 50 秒；`-c copy` 直接复制码流不重编码。改 `-t` 可调整时长，改输出路径即可换文件名。

## 2. 视频抽帧（src/extract_frames.py）

把视频中 10~50 秒段按每 0.2 秒一帧抽出，存入训练集：

```bash
python src/extract_frames.py \
    --video video/sample.mp4 \
    --start 10 --end 50 --interval 0.2 \
    --output datasets/my_dataset/images/train \
    --prefix turn_round
```

多段视频合入同一数据集时，用 `--start-index` 续接编号避免重名，例如第二段视频加 `--start-index 300`。已存在的文件默认跳过，`--overwrite` 覆盖。

标注工具用 labelImg（YOLO 格式）：打开 `images/train` 目录即可，对应的 txt 会写到 `labels/train`。注意两点：

- labels 目录下的 `classes.txt` 保存类别名，是 labelImg 必需的，不要删除（`split_dataset.py` 会自动同步它）。
- **避免全部标成同一个类**：不要勾选左侧"使用默认标签"（勾选后画框不再询问，全部用输入框里的标签）；每次画框确认弹窗里的类别名，它会默认预选上一个用过的标签。
- **避免类别表被改乱**：labelImg 保存时会按它记录的类别重写 `classes.txt`，标注一段时间后检查一下该文件是否还是完整 5 类；如果被改乱，按上面的类别表恢复即可。

## 3. 数据集划分（src/split_dataset.py）

图片标注完成后，按比例随机划分为 train/val/test（默认 7:1:2）：

```bash
python src/split_dataset.py --train 0.7 --val 0.1 --test 0.2 --seed 42
```

按文件名前缀分层切分。也可以只划分某几类新数据（不碰已有数据），例如新标完 go_straight 后按 8:2 划到 train/test：

```bash
python src/split_dataset.py --include go_straight --train 0.8 --val 0 --test 0.2
```

划分是**移动**文件并自动同步 `classes.txt`；不带 `--include` 重复运行前，需先把三个子集合并回 `images/train`、`labels/train`。

## 4. 训练（src/train.py）

```bash
python src/train.py                        # 默认：100 epochs、batch 16、CUDA
python src/train.py --epochs 200 --batch 8 # 自定义轮数；显存不足就调小 batch
```

基于 `models/yolov8n.pt` 微调，训练完最佳权重在 `outputs/train_exp/weights/best.pt`。

⚠️ 数据集含左右镜像的类别（turn_left/turn_right），**水平翻转增强默认已关闭**（`--fliplr 0`，脚本默认值）。若手动调大，翻转后的图会把左转变成右转的样子但标签不变，模型将彻底分不清这两类。训练多次实验对比时，在 `outputs/<实验名>/args.yaml` 里可核对 `fliplr` 等参数。

## 5. 实时检测（src/play.py）

加载训练好的权重做实时检测，视频来源可以是 RTSP 流或本地视频文件：

```bash
python src/play.py                                # 默认连 rtsp://192.168.3.100:8554/test?tcp + 默认权重
python src/play.py --source video/sample.mp4      # 先拿本地视频测试
python src/play.py --model train_noflip           # 指定某次实验的权重
python src/play.py --conf 0.5                     # 调整置信度阈值
```

`--model` 支持三种写法：`best.pt` 路径、实验目录、实验名（如 `train_noflip`）。不指定时默认用 `outputs/train_noflip/weights/best.pt`（fliplr=0 训练的 5 类模型，当前推荐使用），不存在则自动选 outputs 下最新的实验；启动时会打印实际加载的权重路径和类别表，确认无误再开始检测。选哪次实验可看各实验目录下 `results.csv` 里的 `metrics/mAP50(B)` / `metrics/mAP50-95(B)`（best.pt 就是该次验证指标最好的 epoch）；`yolo detect val data=datasets/my_dataset/dataset.yaml model=<权重> split=test` 可查看分类别指标和混淆矩阵。

需要图形界面（`cv2.imshow`），按 `q` 退出；流中断会自动重连。

## 附：旧脚本 src/d1_yolo.py

COCO 预训练模型的 person 检测演示，模型路径是相对路径，**必须从 models/ 目录启动**，否则会联网重新下载权重：

```bash
cd ~/d1_ws/yolo/yolo/models && python ../src/d1_yolo.py
```

日常使用请优先用 `src/play.py`。

## 目录结构

```
├── src/                  # 脚本：play / train / split_dataset / extract_frames / d1_yolo
├── datasets/my_dataset/  # YOLO 数据集（images 与 labels 各含 train/val/test）
├── models/yolov8n.pt     # YOLOv8n COCO 预训练权重
├── video/sample.mp4      # 样例视频
├── outputs/              # 训练产物（best.pt 等）
├── logs/                 # 预留
└── requirements.txt      # 依赖清单
```

更多约定与数据集细节见 [AGENTS.md](AGENTS.md)。
