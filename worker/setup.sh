#!/bin/bash
# Idempotent GPU pod provisioning script.
#
# M3 (look_generation, Qwen-Image-Edit-2511) + M5 (video_generation via LiveAvatar,
# upscale via SeedVR2). Each model gets its OWN venv — their dependency trees conflict
# (different mandated torch/CUDA builds per repo) and the worker's handlers invoke each
# as a subprocess rather than importing them into this process, so isolation is safe.
# LongCat is NOT installed here — the M5 bake-off was budget-scoped to LiveAvatar only;
# see DECISIONS.md.
#
# LiveAvatar/SeedVR2 install under /root, NOT /workspace — found live at M5 build time:
# RunPod's /workspace is a network-mounted volume capped at whatever `volumeInGb` was
# set at pod creation (20GB here), while the pod's root overlay filesystem is the full
# `containerDiskInGb` (150GB) with no separate quota. LiveAvatar's weights alone
# (Wan2.2-S2V-14B, 14B params) blow past a 20GB volume; /root has room. The tradeoff:
# /root doesn't survive a pod restart the way /workspace would — acceptable for this
# single-session correctness test, revisit if a persistent worker pod is ever kept
# running across sessions.
set -euo pipefail

LIVEAVATAR_DIR="${LIVEAVATAR_DIR:-/root/LiveAvatar}"
SEEDVR2_DIR="${SEEDVR2_DIR:-/root/seedvr2_videoupscaler}"

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

echo "=== 5. LiveAvatar (video_generation) — own venv, per its README ==="
if [ ! -d "$LIVEAVATAR_DIR" ]; then
    git clone https://github.com/Alibaba-Quark/LiveAvatar "$LIVEAVATAR_DIR"
fi
cd "$LIVEAVATAR_DIR"
if [ ! -d ".venv" ]; then
    python3.10 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
# Verified via the live README/requirements.txt at M5 build time. A100 = Ampere, not
# Hopper, so FlashAttention 2 (not 3) — the repo's own guidance for non-H800/H200 GPUs.
pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
pip install flash-attn==2.8.3 --no-build-isolation
pip install -r requirements.txt

echo "=== 6. LiveAvatar weights ==="
pip install "huggingface_hub[cli]"
mkdir -p ckpt
huggingface-cli download Wan-AI/Wan2.2-S2V-14B --local-dir ckpt/Wan2.2-S2V-14B
huggingface-cli download Quark-Vision/Live-Avatar --local-dir ckpt/LiveAvatar
deactivate

echo "=== 7. SeedVR2 upscaler — own venv ==="
if [ ! -d "$SEEDVR2_DIR" ]; then
    git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git "$SEEDVR2_DIR"
fi
cd "$SEEDVR2_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
# Deviation from the README's own instructions: it recommends a torch NIGHTLY cu130
# build, but this pod's driver caps at CUDA 12.9 (same bug found and fixed for M3's
# Qwen setup — a CUDA-13 build silently makes torch.cuda.is_available() return False
# instead of raising). Pinning the same verified-working stable cu124 build instead.
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
deactivate

cd "$(dirname "$0")"
echo "=== Setup complete ==="
