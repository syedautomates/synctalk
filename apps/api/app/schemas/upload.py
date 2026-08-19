from typing import Literal

from pydantic import BaseModel

AssetKind = Literal["photo", "reference_video", "voice_sample", "extracted_frame", "garment"]


class PresignRequest(BaseModel):
    kind: AssetKind
    filename: str
    content_type: str


class PresignResponse(BaseModel):
    upload_url: str
    s3_key: str


class AssetCreateRequest(BaseModel):
    kind: AssetKind
    s3_key: str


class ConsentRequest(BaseModel):
    confirmed: bool
