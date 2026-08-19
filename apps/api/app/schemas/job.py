from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

JobStatus = Literal["queued", "leased", "running", "done", "failed"]


class JobOut(BaseModel):
    id: UUID
    type: str
    status: JobStatus
    progress: int
    result: dict | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InternalJobOut(JobOut):
    """Same shape, plus the payload the worker needs to actually run the job."""

    payload: dict


class JobPatchRequest(BaseModel):
    status: JobStatus | None = None
    progress: int | None = None
    heartbeat: bool = False


class JobCompleteRequest(BaseModel):
    result: dict


class JobFailRequest(BaseModel):
    error: str


class InternalPresignRequest(BaseModel):
    prefix: str
    filename: str
    content_type: str


class InternalPresignResponse(BaseModel):
    upload_url: str
    s3_key: str
