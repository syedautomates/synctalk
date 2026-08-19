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
    # Presigned download URLs — candidate_keys/approved_key are raw S3 keys, not
    # fetchable directly by a browser (bucket isn't public). Populated by the route.
    candidate_urls: list[str] = []
    approved_url: str | None = None

    model_config = {"from_attributes": True}
