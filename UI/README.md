# UI 与可视化

- `voice_dashboard.py`：语音转写与巡检状态 HTTP 服务。
- `dashboard.html`：浏览器页面。
- `rviz/`：路径规划、地图、摄像头的 RViz 显示配置。
- `test_dashboard.py`：页面和事件读取测试。

在仓库根目录启动：

```bash
python3 UI/voice_dashboard.py
```

默认监听 `0.0.0.0:8091`。本机访问 `http://127.0.0.1:8091/`，同一局域网使用电脑 IP。只限本机时加 `--host 127.0.0.1`。

页面服务从 `voice_navigation/` 读取实时识别记录和监听状态。只启动页面不会启动麦克风，也不会向机器狗发送指令。导航启动器会自动加载 `rviz/navigation_drive.rviz`。
