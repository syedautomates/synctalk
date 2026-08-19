from dataclasses import dataclass

import anthropic
from pydantic import ValidationError

from app.config import settings
from app.schemas.orchestrator import OrchestratorOutput

MAX_ATTEMPTS = 2
MAX_TOKENS = 8000


@dataclass
class OrchestratorResult:
    output: OrchestratorOutput
    input_tokens: int
    output_tokens: int

# Verbatim from claude.md §8 — do not edit without updating claude.md and logging why
# in DECISIONS.md.
SYSTEM_PROMPT = """You convert a video request into production inputs for a talking-head AI video pipeline.

You receive:
- EMOTION_BRIEF: how the speaker should come across (mood, energy, movement style)
- SCRIPT: the exact words the speaker will say

You output ONLY a JSON object with keys: tagged_script, tts_chunks, style_prompt, negative_notes, emotion_summary.

Rules for tagged_script:
1. NEVER change, add, remove, or reorder the script's words. Your only additions are ElevenLabs v3 audio tags in square brackets and punctuation adjustments for pacing (ellipses, dashes).
2. Insert tags sparingly — one tag per 1–3 sentences maximum. Over-tagging degrades v3 output.
3. Choose tags that realize the EMOTION_BRIEF: e.g. sad → [sad], [sighs], slower punctuation; funny/casual → [laughs], [chuckles], [excited] at genuinely fitting moments only; professional → minimal tags, clean delivery.
4. If the brief implies an emotional arc (e.g. "starts serious, ends hopeful"), distribute tags to follow that arc through the script.

Rules for tts_chunks:
5. Split tagged_script on paragraph boundaries into chunks of at most 2500 characters each. Never split mid-sentence. The concatenation of all chunks must equal tagged_script exactly.

Rules for style_prompt (this drives body/face motion in the video model):
6. Describe ONLY demeanor, energy, gesture style, gaze, and pace — NEVER appearance, clothing, background, or setting (those come from the approved look image and must not be contradicted).
7. Always include the phrase "talking, speaking directly to camera" (the video model needs explicit verbal-action cues for natural lip movement).
8. Map the brief to motion vocabulary: sad → "subdued expression, slow minimal hand gestures, soft gaze"; casual/funny → "relaxed posture, animated natural hand gestures, warm smiling expression"; professional → "composed, measured deliberate gestures, steady eye contact".
9. Keep it under 60 words, comma-separated descriptors.

Rules for negative_notes:
10. List motion behaviors to avoid given the brief (e.g. "no laughing" for somber content).

emotion_summary: one plain sentence describing the delivery you designed, for user confirmation.

Output raw JSON only. No markdown, no commentary."""


class OrchestratorError(Exception):
    """Raised when the orchestrator fails to produce valid output after retrying."""


def _user_content(emotion_brief: str, script: str) -> str:
    return f"EMOTION_BRIEF: {emotion_brief}\n\nSCRIPT:\n{script}"


def orchestrate(emotion_brief: str, script: str) -> OrchestratorResult:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    last_error: Exception | None = None

    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.messages.parse(
                model=settings.orchestrator_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _user_content(emotion_brief, script)}],
                output_format=OrchestratorOutput,
            )
            if response.parsed_output is None:
                raise ValueError(
                    f"Claude returned no parsed output (stop_reason={response.stop_reason})"
                )
            return OrchestratorResult(
                output=response.parsed_output,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        except (ValidationError, anthropic.APIError, ValueError) as exc:
            last_error = exc

    raise OrchestratorError(f"Orchestrator failed after {MAX_ATTEMPTS} attempts: {last_error}")
