from unittest.mock import MagicMock, patch

import anthropic
import pytest
from pydantic import ValidationError

from app.schemas.orchestrator import OrchestratorOutput
from app.services.orchestrator import OrchestratorError, orchestrate

VALID_KWARGS = dict(
    tagged_script="[sad] Hello there. This is a test.",
    tts_chunks=["[sad] Hello there. This is a test."],
    style_prompt="subdued expression, talking, speaking directly to camera, slow gestures",
    negative_notes="no laughing",
    emotion_summary="A subdued, sad delivery.",
)


def test_valid_output_passes_validation() -> None:
    output = OrchestratorOutput(**VALID_KWARGS)
    assert output.tagged_script == VALID_KWARGS["tagged_script"]


def test_chunk_concatenation_mismatch_rejected() -> None:
    bad = {**VALID_KWARGS, "tts_chunks": ["[sad] Hello there.", " This is a DIFFERENT test."]}
    with pytest.raises(ValidationError, match="concatenation"):
        OrchestratorOutput(**bad)


def test_empty_chunks_rejected() -> None:
    bad = {**VALID_KWARGS, "tts_chunks": []}
    with pytest.raises(ValidationError, match="must not be empty"):
        OrchestratorOutput(**bad)


def test_chunk_over_length_limit_rejected() -> None:
    long_script = "a" * 3000
    bad = {**VALID_KWARGS, "tagged_script": long_script, "tts_chunks": [long_script]}
    with pytest.raises(ValidationError, match="2500-char limit"):
        OrchestratorOutput(**bad)


def test_style_prompt_without_talking_rejected() -> None:
    bad = {**VALID_KWARGS, "style_prompt": "subdued expression, slow minimal gestures"}
    with pytest.raises(ValidationError, match="talking"):
        OrchestratorOutput(**bad)


def _mock_client_returning(
    parsed_output: OrchestratorOutput | None, *, raise_error: Exception | None = None
):
    mock_client = MagicMock()
    if raise_error is not None:
        mock_client.messages.parse.side_effect = raise_error
    else:
        mock_response = MagicMock()
        mock_response.parsed_output = parsed_output
        mock_client.messages.parse.return_value = mock_response
    return mock_client


def test_orchestrate_succeeds_on_first_attempt() -> None:
    expected = OrchestratorOutput(**VALID_KWARGS)
    mock_client = _mock_client_returning(expected)
    with patch("app.services.orchestrator.anthropic.Anthropic", return_value=mock_client):
        result = orchestrate("sad, subdued", "Hello there. This is a test.")
    assert result == expected
    assert mock_client.messages.parse.call_count == 1


def test_orchestrate_retries_once_then_succeeds() -> None:
    expected = OrchestratorOutput(**VALID_KWARGS)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed_output = expected
    mock_client.messages.parse.side_effect = [
        anthropic.APIError("transient failure", request=MagicMock(), body=None),
        mock_response,
    ]
    with patch("app.services.orchestrator.anthropic.Anthropic", return_value=mock_client):
        result = orchestrate("sad, subdued", "Hello there. This is a test.")
    assert result == expected
    assert mock_client.messages.parse.call_count == 2


def test_orchestrate_fails_after_max_attempts() -> None:
    mock_client = _mock_client_returning(
        None, raise_error=anthropic.APIError("permanent failure", request=MagicMock(), body=None)
    )
    with patch("app.services.orchestrator.anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(OrchestratorError, match="permanent failure"):
            orchestrate("sad, subdued", "Hello there. This is a test.")
    assert mock_client.messages.parse.call_count == 2
