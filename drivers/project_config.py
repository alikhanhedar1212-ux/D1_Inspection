"""Allow direct script execution from any working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deployment import behavior_path, config_path, map_path, ui_path, local_path, remote_file, ros_prefix, setting, shell_arg, ssh_command
