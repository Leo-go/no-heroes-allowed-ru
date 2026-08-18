#!/bin/bash
set -euo pipefail
cd /home/user/nha-rus
.venv/bin/python tools/build_stage1.py
echo "release: /mnt/b/psp games/No Heroes Allowed RUS/NHA_USA_RUS.iso"
