from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import DbSession
from app.config import settings
from app.schemas.job import (
    InternalJobOut,
    InternalPresignRequest,
    InternalPresignResponse,
    JobCompleteRequest,
    JobFailRequest,
    JobPatchRequest,
)
from app.services import domain_side_effects
from app.services import jobs as jobs_service
from app.services.storage import build_key, presign_put

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])

_worker_bearer = HTTPBearer()


def verify_worker_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_worker_bearer)],
) -> None:
    if credentials.credentials != settings.worker_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token")


WorkerAuth = Annotated[None, Depends(verify_worker_token)]


def _get_job_or_404(db: DbSession, job_id: UUID):
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/jobs/next")
def lease_next_job(_: WorkerAuth, db: DbSession, types: str) -> Response:
    job_types = [t.strip() for t in types.split(",") if t.strip()]
    job = jobs_service.lease_next(db, job_types)
    if job is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    body = jsonable_encoder(InternalJobOut.model_validate(job))
    return JSONResponse(content=body)


@router.patch("/jobs/{job_id}", response_model=InternalJobOut)
def patch_job(job_id: UUID, payload: JobPatchRequest, _: WorkerAuth, db: DbSession):
    job = _get_job_or_404(db, job_id)
    return jobs_service.update(
        db, job, status=payload.status, progress=payload.progress, heartbeat=payload.heartbeat
    )


@router.post("/jobs/{job_id}/complete", response_model=InternalJobOut)
def complete_job(job_id: UUID, payload: JobCompleteRequest, _: WorkerAuth, db: DbSession):
    job = _get_job_or_404(db, job_id)
    job = jobs_service.complete(db, job, payload.result)
    domain_side_effects.apply(db, job, failed=False)
    return job


@router.post("/jobs/{job_id}/fail", response_model=InternalJobOut)
def fail_job(job_id: UUID, payload: JobFailRequest, _: WorkerAuth, db: DbSession):
    job = _get_job_or_404(db, job_id)
    job = jobs_service.fail(db, job, payload.error)
    if job.status == "failed":  # only mark the domain row dead once retries are exhausted
        domain_side_effects.apply(db, job, failed=True)
    return job


@router.post("/uploads/presign", response_model=InternalPresignResponse)
def presign_worker_upload(payload: InternalPresignRequest, _: WorkerAuth):
    s3_key = build_key(payload.prefix, payload.filename)
    url = presign_put(s3_key, payload.content_type)
    return InternalPresignResponse(upload_url=url, s3_key=s3_key)
