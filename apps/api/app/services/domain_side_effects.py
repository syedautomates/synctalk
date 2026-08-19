"""Job completion/failure side effects on domain rows (Look, VideoRequest).

The jobs table is generic — the worker only ever talks to /internal/jobs/*. When a job
finishes, the control plane translates that into an update on the domain row it was
working on, and — for video_generation → upscale — chains the next job automatically
(claude.md §6's "auto-enqueue upscale on completion")."""
from sqlalchemy.orm import Session

from app.db.models import Job, Look, VideoRequest
from app.services import jobs as jobs_service
from app.services.storage import presign_get


def apply(db: Session, job: Job, *, failed: bool) -> None:
    handler = _HANDLERS.get(job.type)
    if handler is not None:
        handler(db, job, failed)


def _on_look_generation(db: Session, job: Job, failed: bool) -> None:
    look_id = job.payload.get("look_id")
    look = db.get(Look, look_id) if look_id else None
    if look is None:
        return
    if failed:
        look.status = "failed"
    else:
        look.candidate_keys = (job.result or {}).get("candidate_keys", [])
        look.status = "generated"
    db.commit()


def _on_video_generation(db: Session, job: Job, failed: bool) -> None:
    video_request = _get_video_request(db, job)
    if video_request is None:
        return
    if failed:
        video_request.status = "failed"
        video_request.error = job.error
        db.commit()
        return

    video_720_key = (job.result or {}).get("video_720_key")
    if not video_720_key or not video_request.audio_key:
        video_request.status = "failed"
        video_request.error = "video_generation completed without a usable output key"
        db.commit()
        return

    video_request.video_720_key = video_720_key
    video_request.status = "upscaling"
    db.commit()

    # Auto-chain upscale — audio comes from this video_request's own stored ElevenLabs
    # audio (audio_key), never the worker's own output.
    jobs_service.enqueue(
        db,
        "upscale",
        {
            "video_request_id": str(video_request.id),
            "video_720_url": presign_get(video_720_key),
            "audio_url": presign_get(video_request.audio_key),
            "output_prefix": f"video_requests/{video_request.id}",
        },
    )


def _on_upscale(db: Session, job: Job, failed: bool) -> None:
    video_request = _get_video_request(db, job)
    if video_request is None:
        return
    if failed:
        video_request.status = "failed"
        video_request.error = job.error
        db.commit()
        return

    result = job.result or {}
    video_request.video_4k_key = result.get("video_4k_key")
    video_request.status = "done"
    ledger = dict(video_request.cost_ledger or {})
    ledger["gpu_seconds_upscale"] = result.get("duration_s")
    video_request.cost_ledger = ledger
    db.commit()


def _get_video_request(db: Session, job: Job) -> VideoRequest | None:
    video_request_id = job.payload.get("video_request_id")
    return db.get(VideoRequest, video_request_id) if video_request_id else None


_HANDLERS = {
    "look_generation": _on_look_generation,
    "video_generation": _on_video_generation,
    "upscale": _on_upscale,
}
