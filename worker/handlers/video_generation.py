"""Talking-head video generation. Branches on VIDEO_MODEL per claude.md M5.

LiveAvatar and LongCat are invoked as subprocesses against their own repo checkouts
(installed by worker/setup.sh under LIVEAVATAR_DIR/LONGCAT_DIR), not imported into
this process — their dependency trees (deepspeed, sam2, insightface, decord,
flash-attn builds...) are heavy and would conflict with look_generation.py's
diffusers env if shared. This also matches claude.md's literal instruction to
"invoke exactly as the repo's scripts do" and "parse the process's segment logs".

Command shapes verified against the live repos at M5 build time — see DECISIONS.md.
The LongCat branch is written to the verified README command shape but was NOT
live-tested (budget-scoped bake-off decision, see DECISIONS.md's M5 entry).
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests

VIDEO_MODEL = os.environ.get("VIDEO_MODEL", "liveavatar")
LIVEAVATAR_DIR = os.environ.get("LIVEAVATAR_DIR", "/root/LiveAvatar")
LONGCAT_DIR = os.environ.get("LONGCAT_DIR", "/root/LongCat-Video")
LIVEAVATAR_ENABLE_COMPILE = os.environ.get("LIVEAVATAR_ENABLE_COMPILE", "false")
# Default false, not the reference script's implicit "true" — verified live at M5
# build time: --fp8 needs Hopper-class native FP8 tensor cores (H800/H200) and fails
# with a Triton "fp8e4nv not supported in this architecture" error on Ampere (A100),
# which claude.md already flagged as FP8/FlashAttention-3-incapable.
LIVEAVATAR_ENABLE_FP8 = os.environ.get("LIVEAVATAR_ENABLE_FP8", "false")
AUDIO_CFG = os.environ.get("AUDIO_CFG", "4")

# "--num_clip" bounds clip count but the finished video never exceeds the audio's
# length regardless (verified against s2v_streaming_interact.py's own argparse help:
# "the whole video will not exceed the length of audio") — safe to leave high.
LIVEAVATAR_NUM_CLIP = int(os.environ.get("LIVEAVATAR_NUM_CLIP", "10000"))
LIVEAVATAR_INFER_FRAMES = int(os.environ.get("LIVEAVATAR_INFER_FRAMES", "48"))

PROGRESS_HEARTBEAT_S = 30


def _download_to(url: str, dest: Path) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def _stream_subprocess(
    cmd: list[str], cwd: str, ctx, heartbeat_progress: int, env: dict | None = None
) -> str:
    """Runs cmd, streaming stdout to the worker log and heartbeating progress every
    ~30s (also renews the job lease) per claude.md's "PATCH progress every 30s"
    instruction. Returns the full combined output; raises with the tail of output
    (claude.md's "last 50 log lines") on a non-zero exit."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    last_report = time.monotonic()
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        print(line, end="", flush=True)
        if time.monotonic() - last_report > PROGRESS_HEARTBEAT_S:
            ctx.report_progress(heartbeat_progress)
            last_report = time.monotonic()
    proc.wait()
    output = "".join(lines)
    if proc.returncode != 0:
        tail = "".join(lines[-50:])
        raise RuntimeError(f"Subprocess failed (exit {proc.returncode}): {cmd}\n{tail}")
    return output


def _run_liveavatar(payload: dict, ctx, work_dir: Path) -> Path:
    image_path = work_dir / "reference.png"
    audio_path = work_dir / "audio.wav"
    _download_to(payload["look_image_url"], image_path)
    _download_to(payload["audio_url"], audio_path)

    output_path = work_dir / "output.mp4"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["ENABLE_COMPILE"] = LIVEAVATAR_ENABLE_COMPILE
    env["NCCL_DEBUG"] = "WARN"
    env["NCCL_DEBUG_SUBSYS"] = "OFF"

    # Full path to the venv's own torchrun, not the bare command name — found live:
    # replacing subprocess.Popen's env wholesale (as above) drops whatever PATH
    # worker.py's own process happened to start with, so a bare "torchrun" silently
    # resolved to the pod image's unrelated system-wide torch install instead of
    # LiveAvatar's venv, which then failed on missing numpy/PIL.
    torchrun_bin = f"{LIVEAVATAR_DIR}/.venv/bin/torchrun"

    cmd = [
        torchrun_bin,
        "--nproc_per_node=1",
        "--master_port=29101",
        "minimal_inference/s2v_streaming_interact.py",
        "--ulysses_size",
        "1",
        "--task",
        "s2v-14B",
        "--size",
        "704*384",
        "--base_seed",
        "420",
        "--training_config",
        "liveavatar/configs/s2v_causal_sft.yaml",
        "--offload_model",
        "True",
        "--convert_model_dtype",
        "--prompt",
        payload["style_prompt"],
        "--image",
        str(image_path),
        "--audio",
        str(audio_path),
        "--infer_frames",
        str(LIVEAVATAR_INFER_FRAMES),
        "--load_lora",
        "--lora_path_dmd",
        "Quark-Vision/Live-Avatar",
        "--sample_steps",
        "4",
        "--sample_guide_scale",
        "0",
        "--num_clip",
        str(LIVEAVATAR_NUM_CLIP),
        "--num_gpus_dit",
        "1",
        "--sample_solver",
        "euler",
        "--single_gpu",
        "--ckpt_dir",
        "ckpt/Wan2.2-S2V-14B/",
        "--save_file",
        str(output_path),
    ]
    if LIVEAVATAR_ENABLE_FP8 == "true":
        cmd.append("--fp8")

    _stream_subprocess(cmd, cwd=LIVEAVATAR_DIR, ctx=ctx, heartbeat_progress=50, env=env)

    if not output_path.exists():
        # The repo's --save_file handling is unverified end-to-end without a live run;
        # fall back to scanning for the newest .mp4 the process produced.
        candidates = sorted(work_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise RuntimeError("LiveAvatar finished but produced no .mp4 output")
        output_path = candidates[-1]
    return output_path


def _run_longcat(payload: dict, ctx, work_dir: Path) -> Path:
    raise NotImplementedError(
        "LongCat fallback is written to the verified README command shape "
        "(run_demo_avatar_single_audio_to_video.py --model_type avatar-v1.5 "
        "--use_distill --use_int8) but was not live-tested — its documented avatar "
        "example requires --context_parallel_size=2 (2 GPUs), which the M5 budget "
        "couldn't cover alongside LiveAvatar. See DECISIONS.md's M5 bake-off entry."
    )


def run(job: dict, ctx) -> dict:
    payload = job["payload"]
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        if VIDEO_MODEL == "liveavatar":
            output_path = _run_liveavatar(payload, ctx, work_dir)
        elif VIDEO_MODEL == "longcat":
            output_path = _run_longcat(payload, ctx, work_dir)
        else:
            raise ValueError(f"Unknown VIDEO_MODEL: {VIDEO_MODEL}")

        ctx.report_progress(90)
        video_bytes = output_path.read_bytes()
        s3_key = ctx.upload_output(
            payload["output_prefix"], "video_720.mp4", video_bytes, "video/mp4"
        )
        ctx.report_progress(100)
        return {"video_720_key": s3_key, "video_model_used": VIDEO_MODEL}
