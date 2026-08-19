#!/bin/bash
# Idempotent GPU pod provisioning script.
#
# M3 (look_generation, Qwen-Image-Edit-2511) + M5 (video_generation via LiveAvatar,
# upscale via SeedVR2) + M7 (LongCat-Video-Avatar-1.5, for the bake-off). Each model
# gets its OWN venv — their dependency trees conflict (different mandated torch/CUDA
# builds per repo) and the worker's handlers invoke each as a subprocess rather than
# importing them into this process, so isolation is safe.
#
# LongCat needs 2 GPUs at inference time (--context_parallel_size=2, verified from its
# own source -- see DECISIONS.md's M7 bake-off entry), unlike LiveAvatar's single-GPU
# offline mode. Its section below is written for a 2-GPU pod; skip it (comment out) if
# provisioning a 1-GPU pod for LiveAvatar-only work.
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
LONGCAT_DIR="${LONGCAT_DIR:-/root/LongCat-Video}"
LONGCAT_WEIGHTS_ROOT="${LONGCAT_WEIGHTS_ROOT:-/root/longcat_weights}"

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
# packaging/wheel/ninja/psutil must be installed before flash-attn's --no-build-isolation
# build runs (its setup.py imports packaging and psutil, and needs wheel to build a
# wheel at all) -- found live at the M7 bake-off, one ModuleNotFoundError at a time
# until all four were installed up front. Same root cause class as LongCat's build
# hitting a missing `wheel` a few lines below.
pip install packaging wheel ninja psutil
pip install flash-attn==2.8.3 --no-build-isolation
pip install -r requirements.txt
# requirements.txt pulls unpinned `deepspeed`, which resolves to a version whose
# transformers.modeling_utils import triggers a circular import against this repo's
# own pinned transformers (<=4.51.3): modeling_utils imports deepspeed, which imports
# transformers.models.opt.modeling_opt, which needs PreTrainedModel from the
# still-initializing modeling_utils module. First found and fixed live at M5 -- that
# fix was never written back into this script, so a fresh pod regressed on it at the
# M7 bake-off. Pinning it here for real this time.
pip install deepspeed==0.15.4

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

echo "=== 8. LongCat-Video-Avatar-1.5 (video_generation fallback, bake-off) — own venv ==="
cd "$(dirname "$0")"
if [ ! -d "$LONGCAT_DIR" ]; then
    git clone https://github.com/meituan-longcat/LongCat-Video "$LONGCAT_DIR"
fi
cd "$LONGCAT_DIR"
if [ ! -d ".venv" ]; then
    python3.10 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
# README recommends a conda env; venv is equivalent for pip installs and matches this
# project's established pattern (LiveAvatar/SeedVR2 also use venv, not conda) -- a
# deviation noted here, not a change to any verified command/flag shape. Its two
# conda-forge installs (librosa, ffmpeg) are covered by requirements_avatar.txt's own
# librosa pin and the pod image's system ffmpeg respectively.
pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
pip install ninja psutil packaging
# --no-build-isolation is required: flash-attn's setup.py imports torch during its own
# build step to determine the CUDA/ABI to target, but pip's default isolated build env
# doesn't have torch installed even though it's already in the outer venv. Missing this
# flag fails with "ModuleNotFoundError: No module named 'torch'" -- found live at the
# M7 bake-off, same class of bug LiveAvatar's flash-attn install already guards against.
# But --no-build-isolation also means the build now runs against THIS venv's packages,
# which need `wheel` installed explicitly -- LongCat's venv didn't have it (LiveAvatar's
# happened to, via some other package's transitive pull), so without this line the
# build instead fails with "ModuleNotFoundError: No module named 'wheel'".
pip install wheel
pip install flash_attn==2.7.4.post1 --no-build-isolation
pip install -r requirements.txt
pip install -r requirements_avatar.txt

echo "=== 9. LongCat weights — avatar-path subset only ==="
# The README's own huggingface-cli commands pull ~158GB (both full repos), but the
# --use_distill --model_type avatar-v1.5 --use_int8 inference path this project uses
# only ever loads ~45GB of that (verified by reading the model-loading source, not
# documented anywhere) -- the base repo's dit/ (54GB) and lora/ (5.7GB) aren't used by
# the avatar path at all, and the avatar repo's bf16 base_model/ (32GB) is unused when
# --use_int8 is passed. --include globs below fetch only what's actually loaded.
pip install "huggingface_hub[cli]"
mkdir -p "$LONGCAT_WEIGHTS_ROOT"
huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 \
    --local-dir "$LONGCAT_WEIGHTS_ROOT/LongCat-Video-Avatar-1.5" \
    --include "base_model_int8/*" "lora/*" "whisper-large-v3/model.safetensors" \
              "whisper-large-v3/*.json" "whisper-large-v3/*.txt" "vocal_separator/*" \
              "scheduler/*" "config.json" "model_index.json"
# The avatar script loads its base tokenizer/text_encoder/vae via a hardcoded
# `../LongCat-Video` relative path from --checkpoint_dir (verified from source) --
# this MUST be a sibling of LongCat-Video-Avatar-1.5 under the same weights root, not
# renamed or relocated independently.
huggingface-cli download meituan-longcat/LongCat-Video \
    --local-dir "$LONGCAT_WEIGHTS_ROOT/LongCat-Video" \
    --include "text_encoder/*" "vae/*" "tokenizer/*" "config.json" "model_index.json"
deactivate

cd "$(dirname "$0")"
echo "=== Setup complete ==="
