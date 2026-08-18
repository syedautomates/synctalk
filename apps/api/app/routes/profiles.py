from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, DbSession
from app.db.models import AvatarProfile, MediaAsset, User
from app.schemas.profile import AssetOut, ChecklistItem, ProfileOut, ReadinessChecklist
from app.schemas.upload import (
    AssetCreateRequest,
    ConsentRequest,
    PresignRequest,
    PresignResponse,
)
from app.services import media_validation
from app.services.frame_extraction import extract_and_store_frames
from app.services.storage import build_object_key, get_object_bytes, object_exists, presign_put

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])

PHOTOS_REQUIRED = 2
REFERENCE_VIDEO_REQUIRED = 1
VOICE_SAMPLE_REQUIRED = 1


def _get_owned_profile(profile_id: UUID, user: User, db: Session) -> AvatarProfile:
    profile = db.get(AvatarProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


def _build_checklist(profile: AvatarProfile, assets: list[MediaAsset]) -> ReadinessChecklist:
    def item(kind: str, required: int) -> ChecklistItem:
        kind_assets = [a for a in assets if a.kind == kind]
        passed = [a for a in kind_assets if a.validation == "passed"]
        return ChecklistItem(
            required=required,
            uploaded=len(kind_assets),
            passed=len(passed),
            ok=len(passed) >= required,
        )

    photos = item("photo", PHOTOS_REQUIRED)
    reference_video = item("reference_video", REFERENCE_VIDEO_REQUIRED)
    voice_sample = item("voice_sample", VOICE_SAMPLE_REQUIRED)
    consent = profile.consent_confirmed_at is not None

    return ReadinessChecklist(
        photos=photos,
        reference_video=reference_video,
        voice_sample=voice_sample,
        consent=consent,
        ready=photos.ok and reference_video.ok and voice_sample.ok and consent,
    )


def _to_profile_out(profile: AvatarProfile, db: Session) -> ProfileOut:
    assets = db.query(MediaAsset).filter(MediaAsset.profile_id == profile.id).all()
    checklist = _build_checklist(profile, assets)
    return ProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        status=profile.status,
        consent_confirmed_at=profile.consent_confirmed_at,
        primary_ref_image_key=profile.primary_ref_image_key,
        created_at=profile.created_at,
        assets=[AssetOut.model_validate(a) for a in assets],
        checklist=checklist,
    )


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(payload: dict, user: CurrentUser, db: DbSession) -> ProfileOut:
    name = payload.get("name")
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is required"
        )

    profile = AvatarProfile(user_id=user.id, name=name, status="draft")
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _to_profile_out(profile, db)


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: UUID, user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = _get_owned_profile(profile_id, user, db)
    return _to_profile_out(profile, db)


@router.post("/{profile_id}/uploads/presign", response_model=PresignResponse)
def presign_upload(
    profile_id: UUID, payload: PresignRequest, user: CurrentUser, db: DbSession
) -> PresignResponse:
    _get_owned_profile(profile_id, user, db)
    s3_key = build_object_key(profile_id, payload.kind, payload.filename)
    url = presign_put(s3_key, payload.content_type)
    return PresignResponse(upload_url=url, s3_key=s3_key)


@router.post("/{profile_id}/consent", response_model=ProfileOut)
def confirm_consent(
    profile_id: UUID, payload: ConsentRequest, user: CurrentUser, db: DbSession
) -> ProfileOut:
    profile = _get_owned_profile(profile_id, user, db)
    if payload.confirmed:
        profile.consent_confirmed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(profile)
    return _to_profile_out(profile, db)


@router.post(
    "/{profile_id}/assets", response_model=ProfileOut, status_code=status.HTTP_201_CREATED
)
def create_asset(
    profile_id: UUID, payload: AssetCreateRequest, user: CurrentUser, db: DbSession
) -> ProfileOut:
    profile = _get_owned_profile(profile_id, user, db)

    if not object_exists(payload.s3_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload not found at that key — did the presigned upload actually complete?",
        )

    data = get_object_bytes(payload.s3_key)

    if payload.kind == "photo":
        result = media_validation.validate_photo(data)
    elif payload.kind == "reference_video":
        result = media_validation.validate_video(data)
    elif payload.kind == "voice_sample":
        result = media_validation.validate_voice(data)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extracted_frame assets are created by the system, not uploaded directly.",
        )

    asset = MediaAsset(
        profile_id=profile_id,
        kind=payload.kind,
        s3_key=payload.s3_key,
        meta=result.meta,
        validation="passed" if result.passed else "failed",
        validation_errors=result.errors or None,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    # On a passing reference video, extract frames and pick the primary reference photo.
    if payload.kind == "reference_video" and result.passed:
        extracted_assets, best_key = extract_and_store_frames(data, profile_id)
        for extracted in extracted_assets:
            db.add(extracted)
        if best_key and profile.primary_ref_image_key is None:
            profile.primary_ref_image_key = best_key
        db.commit()

    return _to_profile_out(profile, db)
