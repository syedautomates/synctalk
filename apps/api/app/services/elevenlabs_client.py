import os
import subprocess
import tempfile

import httpx

from app.config import settings
from app.services.media_validation import ffprobe_info

BASE_URL = "https://api.elevenlabs.io"
V3_MODEL_ID = "eleven_v3"

# eleven_v3's real per-request limit is 5,000 chars (verified against ElevenLabs' docs,
# not the ~10k claude.md guessed at) — leave margin so a chunk never lands right at the edge.
V3_CHAR_LIMIT = 5000
CHUNK_SAFETY_MARGIN = 500
MAX_CHUNK_CHARS = V3_CHAR_LIMIT - CHUNK_SAFETY_MARGIN


class ElevenLabsError(Exception):
    pass


def _headers() -> dict[str, str]:
    return {"xi-api-key": settings.elevenlabs_api_key}


def create_instant_voice_clone(name: str, audio_bytes: bytes, filename: str) -> str:
    """Creates an Instant Voice Clone (IVC) from a single audio sample. Returns voice_id."""
    response = httpx.post(
        f"{BASE_URL}/v1/voices/add",
        headers=_headers(),
        data={"name": name},
        files={"files": (filename, audio_bytes)},
        timeout=60.0,
    )
    if response.status_code != 200:
        raise ElevenLabsError(
            f"Voice clone creation failed ({response.status_code}): {response.text}"
        )
    voice_id: str = response.json()["voice_id"]
    return voice_id


def extract_audio_from_video(video_bytes: bytes) -> bytes:
    """Fallback per claude.md M1/M2: extract the audio track from the reference video
    when no separate voice sample exists."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        video_path = tmp.name
    audio_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-b:a",
                "192k",
                audio_path,
            ],
            check=True,
            capture_output=True,
        )
        with open(audio_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(video_path)
        os.unlink(audio_path)


def _chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries so no chunk exceeds max_chars — never mid-sentence."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text[:max_chars]] if text else []

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def _synthesize_chunk(voice_id: str, text: str, model_id: str) -> bytes:
    response = httpx.post(
        f"{BASE_URL}/v1/text-to-speech/{voice_id}",
        headers={**_headers(), "Content-Type": "application/json"},
        params={"output_format": "mp3_44100_128"},
        json={"text": text, "model_id": model_id},
        timeout=120.0,
    )
    if response.status_code != 200:
        raise ElevenLabsError(f"TTS failed ({response.status_code}): {response.text}")
    return response.content


def _concat_mp3(chunk_paths: list[str]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as filelist:
        for path in chunk_paths:
            escaped = path.replace("'", r"'\''")
            filelist.write(f"file '{escaped}'\n")
        filelist_path = filelist.name

    output_fd = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    output_path = output_fd.name
    output_fd.close()
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                filelist_path,
                "-ar",
                "44100",
                "-c:a",
                "libmp3lame",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        with open(output_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(filelist_path)
        os.unlink(output_path)


def _get_duration(audio_bytes: bytes) -> float:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        duration: float = ffprobe_info(tmp_path)["duration"]
        return duration
    finally:
        os.unlink(tmp_path)


def synthesize(
    voice_id: str, tagged_text: str, model_id: str = V3_MODEL_ID
) -> tuple[bytes, float]:
    """Converts tagged text to speech. Chunks on paragraph boundaries when the text exceeds
    the model's per-request limit, synthesizes each chunk, and concatenates them into one
    seamless mp3 via ffmpeg's concat demuxer. Returns (audio_bytes, duration_seconds)."""
    chunks = _chunk_text(tagged_text)
    if not chunks:
        raise ElevenLabsError("No text to synthesize.")

    chunk_paths: list[str] = []
    try:
        for chunk in chunks:
            audio = _synthesize_chunk(voice_id, chunk, model_id)
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio)
            tmp.close()
            chunk_paths.append(tmp.name)

        if len(chunk_paths) == 1:
            with open(chunk_paths[0], "rb") as f:
                final_audio = f.read()
        else:
            final_audio = _concat_mp3(chunk_paths)

        return final_audio, _get_duration(final_audio)
    finally:
        for path in chunk_paths:
            os.unlink(path)
