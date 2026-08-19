from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, DbSession
from app.config import settings
from app.db.models import AvatarProfile, Look, User, VideoRequest
from app.schemas.video import VideoCreateRequest, VideoCreateResponse, VideoOut
from app.services import idempotency
from app.services import jobs as jobs_service
from app.services.elevenlabs_client import ElevenLabsError, synthesize
from app.services.moderation import ModerationFlagged, moderate
from app.services.orchestrator import OrchestratorError, orchestrate
from app.services.storage import build_key, presign_get, put_object_bytes

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])
# A duplicate submission here would burn real Claude + ElevenLabs + GPU cost -- see
# DECISIONS.md's M7 entry. claude.md's M7 acceptance test names this exact endpoint.
VIDEOS_IDEMPOTENCY_ENDPOINT = "POST /videos"


def _get_owned_profile(profile_id: UUID, user: User, db: Session) -> AvatarProfile:
    profile = db.get(AvatarProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


def _get_owned_video(video_id: UUID, user: User, db: Session) -> VideoRequest:
    video = db.get(VideoRequest, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    profile = db.get(AvatarProfile, video.profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")
    return video


def _to_video_out(video: VideoRequest) -> VideoOut:
    return VideoOut(
        id=video.id,
        profile_id=video.profile_id,
        look_id=video.look_id,
        emotion_brief=video.emotion_brief,
        script=video.script,
        orchestrator_output=video.orchestrator_output,
        status=video.status,
        error=video.error,
        cost_ledger=video.cost_ledger,
        created_at=video.created_at,
        video_720_url=presign_get(video.video_720_key) if video.video_720_key else None,
        video_4k_url=presign_get(video.video_4k_key) if video.video_4k_key else None,
    )


@router.post("", response_model=VideoCreateResponse, status_code=status.HTTP_201_CREATED)
def create_video(
    payload: VideoCreateRequest,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> VideoCreateResponse:
    cached = idempotency.get_cached(db, idempotency_key, VIDEOS_IDEMPOTENCY_ENDPOINT)
    if cached is not None:
        return VideoCreateResponse.model_validate(cached.body)
    if idempotency_key is not None and not idempotency.claim(
        db, idempotency_key, VIDEOS_IDEMPOTENCY_ENDPOINT
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is already in progress.",
        )

    try:
        try:
            moderate(payload.emotion_brief, context="emotion/movement brief")
            moderate(payload.script, context="video script")
        except ModerationFlagged as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc

        profile = _get_owned_profile(payload.profile_id, user, db)

        look = db.get(Look, payload.look_id)
        if look is None or look.profile_id != profile.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look not found")
        if look.approved_key is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This look has no approved candidate yet — approve one first.",
            )

        # claude.md M2: the default American stock voice is used before the profile has
        # its own clone, so the pipeline is testable end-to-end without a voice clone.
        voice_id = profile.elevenlabs_voice_id or settings.elevenlabs_default_voice_id

        video_request = VideoRequest(
            profile_id=profile.id,
            look_id=look.id,
            emotion_brief=payload.emotion_brief,
            script=payload.script,
            status="orchestrating",
        )
        db.add(video_request)
        db.commit()
        db.refresh(video_request)

        try:
            result = orchestrate(payload.emotion_brief, payload.script)
        except OrchestratorError as exc:
            video_request.status = "failed"
            video_request.error = f"Orchestrator failed: {exc}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=video_request.error
            ) from exc

        video_request.orchestrator_output = result.output.model_dump()
        video_request.status = "tts"
        video_request.cost_ledger = {
            "claude_input_tokens": result.input_tokens,
            "claude_output_tokens": result.output_tokens,
        }
        db.commit()

        try:
            audio_bytes, audio_duration_s = synthesize(voice_id, result.output.tagged_script)
        except ElevenLabsError as exc:
            video_request.status = "failed"
            video_request.error = f"TTS failed: {exc}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=video_request.error
            ) from exc

        audio_key = build_key(f"video_requests/{video_request.id}", "audio.mp3")
        put_object_bytes(audio_key, audio_bytes, "audio/mpeg")

        video_request.audio_key = audio_key
        video_request.status = "rendering"
        ledger = dict(video_request.cost_ledger)
        ledger["elevenlabs_chars"] = len(result.output.tagged_script)
        ledger["audio_duration_s"] = audio_duration_s
        video_request.cost_ledger = ledger
        db.commit()

        job = jobs_service.enqueue(
            db,
            "video_generation",
            {
                "video_request_id": str(video_request.id),
                "look_image_url": presign_get(look.approved_key),
                "audio_url": presign_get(audio_key),
                "style_prompt": result.output.style_prompt,
                "output_prefix": f"video_requests/{video_request.id}",
            },
        )
        response = VideoCreateResponse(video_request_id=video_request.id, job_id=job.id)
    except Exception:
        if idempotency_key is not None:
            idempotency.release(db, idempotency_key, VIDEOS_IDEMPOTENCY_ENDPOINT)
        raise

    if idempotency_key is not None:
        idempotency.store_result(
            db,
            idempotency_key,
            VIDEOS_IDEMPOTENCY_ENDPOINT,
            status.HTTP_201_CREATED,
            response.model_dump(mode="json"),
        )
    return response


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: UUID, user: CurrentUser, db: DbSession) -> VideoOut:
    video = _get_owned_video(video_id, user, db)
    return _to_video_out(video)
