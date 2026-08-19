from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LookCreateRequest(BaseModel):
    prompt: str
    garment_asset_id: UUID | None = None


class LookCreateResponse(BaseModel):
    look_id: UUID
    job_id: UUID


class LookApproveRequest(BaseModel):
    candidate_key: str


class LookOut(BaseModel):
    id: UUID
    profile_id: UUID
    prompt: str
    garment_asset_id: UUID | None
    candidate_keys: list[str]
    approved_key: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
