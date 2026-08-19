#!/bin/bash
# Idempotent GPU pod provisioning script.
#
# M3 scope only: installs what look_generation.py (Qwen-Image-Edit-2511) needs and smoke
# tests that the pipeline loads. Does NOT install LiveAvatar/LongCat/SeedVR2 — those are
# M5's job, per claude.md; extend this script then rather than front-loading it now.
set -euo pipefail

echo "=== 1. GPU check ==="
if ! command -v nvidia-smi &> /dev/null; then
    echo "FATAL: nvidia-smi not found — no NVIDIA GPU visible on this pod." >&2
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "=== 2. Python env ==="
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip

echo "=== 3. Install worker requirements (diffusers from git, per HF model card) ==="
pip install -r requirements.txt

echo "=== 4. Smoke test: pipeline class importable, CUDA visible to torch ==="
python3 - <<'EOF'
import torch
from diffusers import QwenImageEditPlusPipeline

assert torch.cuda.is_available(), "torch does not see a CUDA device"
print(f"torch sees CUDA: {torch.cuda.get_device_name(0)}")
print("QwenImageEditPlusPipeline import OK")
EOF

echo "=== Setup complete ==="
