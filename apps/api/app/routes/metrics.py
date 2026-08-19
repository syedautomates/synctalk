from fastapi import APIRouter
from sqlalchemy import func, select

from app.auth import CurrentUser, DbSession
from app.db.models import AvatarProfile, Job, Look, VideoRequest
from app.schemas.metrics import MetricsOut

router = APIRouter(prefix="/api/v1", tags=["metrics"])


def _counts_by(db: DbSession, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {value: count for value, count in rows}


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(_user: CurrentUser, db: DbSession) -> MetricsOut:
    return MetricsOut(
        profiles_total=db.scalar(select(func.count()).select_from(AvatarProfile)) or 0,
        looks_total=db.scalar(select(func.count()).select_from(Look)) or 0,
        looks_by_status=_counts_by(db, Look.status),
        video_requests_total=db.scalar(select(func.count()).select_from(VideoRequest)) or 0,
        video_requests_by_status=_counts_by(db, VideoRequest.status),
        jobs_by_status=_counts_by(db, Job.status),
        jobs_by_type=_counts_by(db, Job.type),
    )
