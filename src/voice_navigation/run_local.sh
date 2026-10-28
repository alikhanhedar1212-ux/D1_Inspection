#!/usr/bin/env bash
set -e
voice_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
voice_python="${D1_PYTHON:-}"
if [[ -z "$voice_python" ]]; then
    if [[ -x "$voice_root/.venv/bin/python" ]]; then
        voice_python="$voice_root/.venv/bin/python"
    else
        voice_python=python3
    fi
fi
exec "$voice_python" -u "$voice_root/voice_navigation.py" --local "$@"
