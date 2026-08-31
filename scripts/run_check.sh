#!/usr/bin/env bash
# Windows-side wrapper for running agent/check.sh outside Docker.
# Use with Git Bash (C:\Program Files\Git\bin\bash.exe), which forwards the
# Windows environment to python.exe natively. PYTHONPATH points at a minimal
# spoon_ai stub so the real (heavy) SDK is not required on the host.
set -u
export PYTHONPATH="C:/Users/ASUS/Desktop/rspc/qwerty-AI/logs/spoon_ai_stub"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
bash agent/check.sh
exit $?