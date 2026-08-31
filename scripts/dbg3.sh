#!/usr/bin/env bash
set -u
S="$(mktemp -d)"
ln -sf /mnt/c/Users/ASUS/AppData/Local/Programs/Python/Python313/python.exe "$S/python"
export PATH="$S:$PATH"
export WSLENV=PYTHONPATH/u
export PYTHONPATH="/mnt/c/Users/ASUS/Desktop/rspc/qwerty-AI/logs/spoon_ai_stub"
python -c "import os; print('ENV PYTHONPATH=', os.environ.get('PYTHONPATH')); import spoon_ai; print('STUB OK', spoon_ai.__file__)"