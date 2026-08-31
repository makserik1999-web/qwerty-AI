#!/usr/bin/env bash
set -u
S="$(mktemp -d)"
ln -sf /mnt/c/Users/ASUS/AppData/Local/Programs/Python/Python313/python.exe "$S/python"
export PATH="$S:$PATH"
export PYTHONPATH="C:/Users/ASUS/Desktop/rspc/qwerty-AI/logs/spoon_ai_stub"
python -c "import os, sys; print('ENV PYTHONPATH=', os.environ.get('PYTHONPATH')); print(sys.path[:5])"