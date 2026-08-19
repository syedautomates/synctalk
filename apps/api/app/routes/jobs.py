from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentUser, DbSession
from app.schemas.job import JobOut
from app.services import jobs as jobs_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, _user: CurrentUser, db: DbSession) -> JobOut:
    job = jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobOut.model_validate(job)
