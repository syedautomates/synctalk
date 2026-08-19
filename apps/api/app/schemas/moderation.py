from pydantic import BaseModel, Field


class ModerationResult(BaseModel):
    flagged: bool = Field(..., description="True if the content should be refused")
    reason: str = Field(..., description="One-sentence explanation; empty string if not flagged")
