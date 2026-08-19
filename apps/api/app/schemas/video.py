from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VideoCreateRequest(BaseModel):
    profile_id: UUID
    look_id: UUID
    emotion_brief: str
    script: str


class VideoCreateResponse(BaseModel):
    video_request_id: UUID
    job_id: UUID


class VideoOut(BaseModel):
    id: UUID
    profile_id: UUID
    look_id: UUID
    emotion_brief: str
    script: str
    orchestrator_output: dict | None
    status: str
    error: str | None
    cost_ledger: dict
    created_at: datetime
    # Presigned download URLs, only populated once the corresponding stage has output.
    video_720_url: str | None = None
    video_4k_url: str | None = None

    model_config = {"from_attributes": True}
