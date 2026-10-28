#!/usr/bin/env bash
set -e
voice_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$voice_root/../navigation_localization/runtime_env.sh"
exec "$voice_root/.venv/bin/python" -u "$voice_root/voice_navigation.py" "$@"
