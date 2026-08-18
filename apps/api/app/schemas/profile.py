from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ProfileCreate(BaseModel):
    name: str


class AssetOut(BaseModel):
    id: UUID
    kind: str
    s3_key: str
    meta: dict
    validation: str
    validation_errors: list[str] | None

    model_config = {"from_attributes": True}


class ChecklistItem(BaseModel):
    required: int
    uploaded: int
    passed: int
    ok: bool


class ReadinessChecklist(BaseModel):
    photos: ChecklistItem
    reference_video: ChecklistItem
    voice_sample: ChecklistItem
    consent: bool
    ready: bool


class ProfileOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    status: str
    consent_confirmed_at: datetime | None
    primary_ref_image_key: str | None
    created_at: datetime
    assets: list[AssetOut]
    checklist: ReadinessChecklist

    model_config = {"from_attributes": True}
