from unittest.mock import MagicMock, patch

import anthropic
import pytest

from app.schemas.moderation import ModerationResult
from app.services.moderation import ModerationFlagged, moderate


def _mock_client_returning(result: ModerationResult | None) -> MagicMock:
    mock_response = MagicMock()
    mock_response.parsed_output = result
    mock_response.stop_reason = "end_turn"
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = mock_response
    return mock_client


def test_flagged_content_raises() -> None:
    result = ModerationResult(flagged=True, reason="Depicts a different named public figure.")
    mock_client = _mock_client_returning(result)
    with patch("app.services.moderation.anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(ModerationFlagged, match="Depicts a different named public figure"):
            moderate("make me look like a famous celebrity", context="look prompt")


def test_clean_content_passes() -> None:
    result = ModerationResult(flagged=False, reason="")
    mock_client = _mock_client_returning(result)
    with patch("app.services.moderation.anthropic.Anthropic", return_value=mock_client):
        moderate("tech home office, black polo shirt", context="look prompt")  # no raise


def test_api_error_fails_open() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.side_effect = anthropic.APIError(
        "transient failure", request=MagicMock(), body=None
    )
    with patch("app.services.moderation.anthropic.Anthropic", return_value=mock_client):
        moderate("anything", context="look prompt")  # no raise -- fails open per design


def test_unparseable_response_fails_open() -> None:
    mock_client = _mock_client_returning(None)
    with patch("app.services.moderation.anthropic.Anthropic", return_value=mock_client):
        moderate("anything", context="look prompt")  # no raise -- fails open per design
