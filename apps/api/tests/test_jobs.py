"""Lease-reclaim behavior against a real Postgres session -- claude.md's M7 acceptance
test is literally "kill the worker mid-render -> job is reclaimed and retried once ->
completes", which is SELECT ... FOR UPDATE SKIP LOCKED + unique-constraint semantics
that a mocked Session can't meaningfully stand in for. Note: jobs.py's functions each
commit their own transaction, so these tests leave terminal (done/failed) rows behind
across runs -- harmless, since lease_next only ever selects queued/lease-expired rows.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import Job
from app.services import jobs as jobs_service


def test_expired_lease_is_reclaimed_and_completes(db: Session) -> None:
    job_type = "test_lease_reclaim"
    job = jobs_service.enqueue(db, job_type, {})

    leased = jobs_service.lease_next(db, [job_type])
    assert leased is not None
    assert leased.id == job.id
    assert leased.attempts == 1

    # Simulate a worker that crashed mid-render and never sent a heartbeat.
    leased.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    reclaimed = jobs_service.lease_next(db, [job_type])
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.attempts == 2

    completed = jobs_service.complete(db, reclaimed, {"ok": True})
    assert completed.status == "done"


def test_lease_exhaustion_marks_job_permanently_failed(db: Session) -> None:
    job_type = "test_lease_exhaustion"
    job = jobs_service.enqueue(db, job_type, {})

    for _ in range(2):
        leased = jobs_service.lease_next(db, [job_type])
        assert leased is not None and leased.id == job.id
        leased.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    # A third lease attempt exceeds MAX_ATTEMPTS -- must not retry forever.
    assert jobs_service.lease_next(db, [job_type]) is None

    dead = db.get(Job, job.id)
    assert dead is not None
    assert dead.status == "failed"
    assert dead.attempts == 3
