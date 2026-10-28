#!/usr/bin/env bash
set -e
voice_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$voice_root/run.sh" --computer-mic "$@"
