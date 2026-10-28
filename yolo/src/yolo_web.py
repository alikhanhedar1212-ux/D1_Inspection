#!/usr/bin/env python3
"""
YOLO 检测网页直播：读取 RTSP 流或本地视频，实时推理并把带标注框的画面
以 MJPEG 视频流的形式提供给浏览器播放，局域网内任何设备打开网页即可观看。

推理在独立线程中进行，始终只保留最新一帧，多个浏览器同时观看不会
增加推理负担。模型路径解析与 play.py 一致。

用法示例：
    python yolo_web.py                                # 默认 RTSP + 默认权重，端口 8092
    python yolo_web.py --source video/sample.mp4      # 用本地视频测试
    python yolo_web.py --port 9000 --conf 0.6

观看方式：浏览器打开 http://<本机IP>:8092/ （同局域网手机/电脑均可）。
嵌入其他网页：<img src="http://<本机IP>:8092/video"> 或 <iframe>。
"""

import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 与 play.py 共用的模型路径解析（支持路径/实验目录/实验名/自动回退）
from play import resolve_model_path

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>YOLO 检测画面</title>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:sans-serif;
         display:flex; flex-direction:column; align-items:center; }}
  h1 {{ font-size:18px; margin:12px 0 8px; }}
  img {{ max-width:96vw; max-height:85vh; border:1px solid #444; }}
</style>
</head>
<body>
<h1>YOLO 实时检测（{model}）</h1>
<img src="/video" alt="检测画面">
</body>
</html>
"""

# 最新一帧 JPEG（bytes），推理线程写、各播放线程读
_frame_lock = threading.Lock()
_latest_jpg = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="YOLO 检测网页直播：RTSP/本地视频 → 推理 → 浏览器 MJPEG 播放。"
    )
    parser.add_argument(
        "--source", "-s",
        type=str,
        default="rtsp://192.168.3.100:8554/test?tcp",
        help="视频来源：RTSP 地址或本地视频文件路径，"
             "默认 rtsp://192.168.3.100:8554/test?tcp。",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="模型权重：best.pt 路径、实验目录或实验名；"
             "不指定时同 play.py 的默认选择逻辑。",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.5,
        help="置信度阈值，默认 0.5。",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8092,
        help="HTTP 服务端口，默认 8092。",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="监听地址，默认 0.0.0.0（局域网可访问）；仅本机可访问填 127.0.0.1。",
    )
    return parser.parse_args()


def inference_loop(args, model_path):
    """取流 + 推理 + 标注，把最新帧编码为 JPEG 供播放线程分发。"""
    import cv2
    from ultralytics import YOLO

    model = YOLO(model_path)
    print(f"加载模型：{model_path}")
    print(f"检测类别：{model.names}")

    cap = cv2.VideoCapture(args.source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    while True:
        # 连续读 3 帧只保留最后一帧，降低延迟
        ret = False
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
                name = model.names[int(box.cls[0])]
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                cv2.putText(frame, f'{name} {conf:.2f}', (int(x1), int(y1) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with _frame_lock:
                global _latest_jpg
                _latest_jpg = buf.tobytes()


class StreamHandler(BaseHTTPRequestHandler):
    server_version = "YOLOWeb/1.0"

    def log_message(self, fmt, *log_args):
        pass  # 静音访问日志

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML_PAGE.format(model=os.path.basename(self.server.model_path)) \
                .encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/video":
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while True:
                with _frame_lock:
                    jpg = _latest_jpg
                if jpg:
                    try:
                        self.wfile.write(b"--frame\r\n"
                                         b"Content-Type: image/jpeg\r\n"
                                         b"Content-Length: " + str(len(jpg)).encode()
                                         + b"\r\n\r\n" + jpg + b"\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                time.sleep(0.05)  # 约 20fps，只回放最新帧
        else:
            self.send_response(404)
            self.end_headers()


def main():
    args = parse_args()
    model_path = resolve_model_path(args.model)
    print(f"视频来源：{args.source}")
    print(f"网页地址：http://<本机IP>:{args.port}/")

    try:
        import cv2  # noqa: F401  提前验证依赖
    except ImportError:
        sys.exit("错误：需要安装 opencv-python，请运行 `pip install opencv-python`。")

    worker = threading.Thread(target=inference_loop, args=(args, model_path),
                              daemon=True)
    worker.start()

    server = ThreadingHTTPServer((args.host, args.port), StreamHandler)
    server.model_path = model_path  # 供首页显示模型名
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
