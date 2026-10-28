#!/usr/bin/env bash
set -e
voice_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$voice_root/.venv/bin/python" -u "$voice_root/voice_navigation.py" --local "$@"
