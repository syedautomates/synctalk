"""Content gate for look prompts and video scripts (claude.md M7).

The primary safety guarantee is architectural: every AvatarProfile is bound to one
consented owner (see the consent gate in routes/profiles.py), and every generation
uses that owner's own reference photos/video/voice -- there's no way to feed the
pipeline someone else's likeness even if the prompt asked for one. This is a
defense-in-depth text check on top of that, per claude.md's explicit instruction to
add a Claude-based moderation check on look prompts (and, by the same section's
framing, video scripts) for impersonation/NSFW.
"""

import logging

import anthropic
from pydantic import ValidationError

from app.config import settings
from app.schemas.moderation import ModerationResult

logger = logging.getLogger(__name__)

MODERATION_SYSTEM_PROMPT = """You are a content moderation gate for a self-hosted \
talking-head avatar video generator.

Every avatar profile is bound to its owner's own consented likeness and voice \
(consent is enforced elsewhere, outside what you see) -- this generator must only \
ever be used to depict that one person, never anyone else.

You will be shown either a scene-generation prompt (background/setting/outfit for a \
photo of the profile owner) or a video script the profile owner will speak on camera.

Flag (flagged=true) ONLY if the text:
- Names or clearly describes a DIFFERENT specific real person (a celebrity, a named \
individual, "make me look like <public figure>", impersonating someone else) -- \
generic style references ("photorealistic", "like a magazine photo", a named brand \
of clothing) are fine.
- Requests sexual, nude, or otherwise NSFW visual content.
- Requests depicting someone OTHER than the profile owner (e.g. combining the \
owner's likeness with another named or described person).

Do NOT flag ordinary scene descriptions, clothing, settings, camera/mic gear, \
emotional tone, or the literal content of a script the person is choosing to say \
about themselves -- including scripts with strong opinions, sales pitches, or claims \
the speaker is making about themselves. This is not a general profanity/opinion filter.

Output ONLY a JSON object: {"flagged": bool, "reason": string}. reason is a \
one-sentence explanation when flagged, or an empty string when not flagged. No \
markdown, no commentary."""

MAX_TOKENS = 300


class ModerationFlagged(Exception):
    """Raised when a look prompt or video script should be refused."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def moderate(text: str, *, context: str) -> None:
    """Raises ModerationFlagged if `text` should be refused.

    `context` is a short label ("look prompt" / "video script") folded into the
    raised error's message for the caller to surface to the user.

    Fails open (allows the request through, logs a warning) on an Anthropic API
    error or an unparseable response -- the architectural consent-binding is the
    real safety guarantee; this text check is defense-in-depth on top of it, and a
    transient API hiccup shouldn't block the whole product for its single owner-user.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.parse(
            model=settings.orchestrator_model,
            max_tokens=MAX_TOKENS,
            system=MODERATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            output_format=ModerationResult,
        )
    except (anthropic.APIError, ValidationError) as exc:
        logger.warning("moderation check failed for %s, failing open: %s", context, exc)
        return

    result = response.parsed_output
    if result is None:
        logger.warning(
            "moderation check for %s returned no parsed output (stop_reason=%s), failing open",
            context,
            response.stop_reason,
        )
        return

    if result.flagged:
        raise ModerationFlagged(
            f"This {context} was flagged and can't be used: {result.reason}"
        )
