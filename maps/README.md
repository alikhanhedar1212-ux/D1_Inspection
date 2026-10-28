# 地图与点位

- `map.yaml` / `map.pgm`：当前导航地图；YAML 中的图像路径相对于本目录。
- `map_cleaned.pgm`：清理后的地图副本。
- `waypoints.yaml`：原六个语音导航点的位置和朝向。
- `patrol_config.json`：P1～P4、巡检顺序、返回路线和到点判定配置。

P2 当前与 2 号洗手间位置和方向一致，第二站的 `stop_overrides` 仍动态读取 `waypoints.yaml` 的 2 号点。

地图属于原现场。换场地时在本目录更新地图、原点及点位，不需要改脚本路径。底层控制和定位参数在 `drivers/config/`。
