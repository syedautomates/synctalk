from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Job

LEASE_MINUTES = 15
MAX_ATTEMPTS = 2


def enqueue(db: Session, job_type: str, payload: dict) -> Job:
    job = Job(type=job_type, payload=payload, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def lease_next(db: Session, types: list[str]) -> Job | None:
    """Leases the oldest eligible job: a queued job, or a leased/running job whose
    lease expired (a crashed or killed worker never checked back in). Reclaimed jobs
    count against the same attempts budget as an explicit failure."""
    now = datetime.now(timezone.utc)

    while True:
        stmt = (
            select(Job)
            .where(
                Job.type.in_(types),
                or_(
                    Job.status == "queued",
                    and_(Job.status.in_(["leased", "running"]), Job.lease_expires_at < now),
                ),
            )
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.execute(stmt).scalar_one_or_none()
        if job is None:
            return None

        job.attempts += 1
        if job.attempts > MAX_ATTEMPTS:
            job.status = "failed"
            job.error = "Exceeded max attempts (lease expired without completing)."
            job.lease_expires_at = None
            db.commit()
            continue  # this one's dead, look for the next eligible job

        job.status = "leased"
        job.lease_expires_at = now + timedelta(minutes=LEASE_MINUTES)
        db.commit()
        db.refresh(job)
        return job


def update(
    db: Session,
    job: Job,
    *,
    status: str | None = None,
    progress: int | None = None,
    heartbeat: bool = False,
) -> Job:
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = max(0, min(100, progress))
    if heartbeat:
        job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=LEASE_MINUTES)
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job: Job, result: dict) -> Job:
    job.status = "done"
    job.progress = 100
    job.result = result
    job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    return job


def fail(db: Session, job: Job, error: str) -> Job:
    job.error = error
    if job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
        job.lease_expires_at = None
    else:
        job.status = "queued"  # available for immediate retry
        job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: UUID) -> Job | None:
    return db.get(Job, job_id)
