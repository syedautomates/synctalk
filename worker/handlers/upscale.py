"""4K upscale via SeedVR2's standalone CLI (numz/ComfyUI-SeedVR2_VideoUpscaler),
then mux the original ElevenLabs audio back in. CLI flags verified against the
live README at M5 build time — see DECISIONS.md.
"""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests

SEEDVR2_DIR = os.environ.get("SEEDVR2_DIR", "/root/seedvr2_videoupscaler")
SEEDVR2_PYTHON = os.environ.get("SEEDVR2_PYTHON", f"{SEEDVR2_DIR}/.venv/bin/python")
SEEDVR2_VARIANT = os.environ.get("SEEDVR2_VARIANT", "3b_fp16")
TARGET_SHORT_SIDE = int(os.environ.get("TARGET_SHORT_SIDE_PX", "2160"))
BATCH_SIZE = int(os.environ.get("SEEDVR2_BATCH_SIZE", "5"))  # must be 4n+1

# claude.md: "Verify output duration matches audio duration ±0.2s."
MAX_DURATION_DRIFT_S = 0.2

PROGRESS_HEARTBEAT_S = 30

_DIT_MODEL_FILES = {
    "3b_fp16": "seedvr2_ema_3b_fp16.safetensors",
    "3b_fp8": "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
}


def _download_to(url: str, dest: Path) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def _stream_subprocess(cmd: list[str], cwd: str, ctx, heartbeat_progress: int) -> None:
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
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
    if proc.returncode != 0:
        tail = "".join(lines[-50:])
        raise RuntimeError(f"Subprocess failed (exit {proc.returncode}): {cmd}\n{tail}")


def _ffprobe_duration(path: Path, stream: str | None = None) -> float:
    """Duration of one stream (e.g. "v:0"/"a:0") if given, else the container's overall
    duration. Found live: the container-level ("-show_format") duration follows the
    LONGEST stream, not the video track — muxing a short video against long audio with
    no -shortest silently produces a valid-looking file whose container duration
    matches the audio while the video freezes partway through. Always check the video
    stream's own duration against the audio, never the container duration, to catch
    this."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json"]
    if stream is not None:
        cmd += ["-select_streams", stream, "-show_entries", "stream=duration"]
    else:
        cmd += ["-show_format"]
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)
    if stream is not None:
        return float(data["streams"][0]["duration"])
    return float(data["format"]["duration"])


def run(job: dict, ctx) -> dict:
    payload = job["payload"]
    dit_model = _DIT_MODEL_FILES.get(SEEDVR2_VARIANT, _DIT_MODEL_FILES["3b_fp16"])

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        input_video = work_dir / "input_720.mp4"
        original_audio = work_dir / "original_audio.mp3"
        _download_to(payload["video_720_url"], input_video)
        _download_to(payload["audio_url"], original_audio)
        ctx.report_progress(10)

        upscaled_video = work_dir / "upscaled.mp4"
        cmd = [
            SEEDVR2_PYTHON,
            "inference_cli.py",
            str(input_video),
            "--output",
            str(upscaled_video),
            "--resolution",
            str(TARGET_SHORT_SIDE),
            "--dit_model",
            dit_model,
            "--batch_size",
            str(BATCH_SIZE),
            "--video_backend",
            "ffmpeg",
        ]
        _stream_subprocess(cmd, cwd=SEEDVR2_DIR, ctx=ctx, heartbeat_progress=40)
        if not upscaled_video.exists():
            raise RuntimeError("SeedVR2 finished but produced no output file")
        ctx.report_progress(70)

        # Check BEFORE muxing, against the video stream's own duration — catches a
        # too-short video (e.g. video_generation stopped before covering the full
        # audio) as a clear failure instead of silently shipping a file whose video
        # freezes partway through while audio keeps playing.
        audio_duration = _ffprobe_duration(original_audio)
        upscaled_video_duration = _ffprobe_duration(upscaled_video, stream="v:0")
        drift = abs(upscaled_video_duration - audio_duration)
        if drift > MAX_DURATION_DRIFT_S:
            raise RuntimeError(
                f"Upscaled video duration ({upscaled_video_duration:.3f}s) drifts "
                f"{drift:.3f}s from audio duration ({audio_duration:.3f}s), over the "
                f"{MAX_DURATION_DRIFT_S}s limit — video_generation likely didn't cover "
                "the full audio track."
            )

        # Mux the ORIGINAL ElevenLabs audio back in — SeedVR2's own output audio (if
        # any) is not the source of truth. -c:v copy avoids a second lossy re-encode.
        final_video = work_dir / "final_4k.mp4"
        mux_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(upscaled_video),
            "-i",
            str(original_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(final_video),
        ]
        subprocess.run(mux_cmd, check=True, capture_output=True, text=True)
        ctx.report_progress(90)

        video_bytes = final_video.read_bytes()
        s3_key = ctx.upload_output(
            payload["output_prefix"], "video_4k.mp4", video_bytes, "video/mp4"
        )
        ctx.report_progress(100)
        return {"video_4k_key": s3_key, "duration_s": upscaled_video_duration}
