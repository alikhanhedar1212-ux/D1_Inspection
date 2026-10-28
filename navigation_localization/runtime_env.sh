#!/usr/bin/env bash
# Source this file from any working directory. System ROS packages are supported.
NAV_RUNTIME_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NAV_ROS_SETUP="${D1_ROS_SETUP:-$(python3 "$NAV_RUNTIME_ROOT/../deployment.py" --get ros_setup)}"
NAV_ROS_SETUP="${NAV_ROS_SETUP/#\~/$HOME}"
if [[ ! -f "$NAV_ROS_SETUP" ]]; then
    echo "ROS setup not found: $NAV_ROS_SETUP (set D1_ROS_SETUP)" >&2
    return 1
fi
source "$NAV_ROS_SETUP"
NAV_CYCLONE_PREFIX="$NAV_RUNTIME_ROOT/vendor/cyclone/opt/ros/humble"
if [[ -d "$NAV_CYCLONE_PREFIX" ]]; then
    export AMENT_PREFIX_PATH="$NAV_CYCLONE_PREFIX:${AMENT_PREFIX_PATH:-}"
    export LD_LIBRARY_PATH="$NAV_CYCLONE_PREFIX/lib:$NAV_CYCLONE_PREFIX/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1
export CYCLONEDDS_URI="file://$NAV_RUNTIME_ROOT/cyclonedds.xml"
