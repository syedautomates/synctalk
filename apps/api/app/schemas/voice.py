from uuid import UUID

from pydantic import BaseModel


class CreateVoiceRequest(BaseModel):
    source_asset_id: UUID | None = None
    use_reference_video: bool = False
