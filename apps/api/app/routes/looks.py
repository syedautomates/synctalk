import random
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, DbSession
from app.db.models import AvatarProfile, Look, MediaAsset, User
from app.schemas.look import LookApproveRequest, LookCreateRequest, LookCreateResponse, LookOut
from app.services import idempotency
from app.services import jobs as jobs_service
from app.services.moderation import ModerationFlagged, moderate
from app.services.storage import presign_get

router = APIRouter(prefix="/api/v1", tags=["looks"])

EXTRA_REFERENCE_PHOTOS = 2
CANDIDATE_COUNT = 4
# A duplicate submission here would burn a real GPU job (look_generation, M3) -- see
# DECISIONS.md's M7 entry.
LOOKS_IDEMPOTENCY_ENDPOINT = "POST /profiles/{id}/looks"


def _get_owned_profile(profile_id: UUID, user: User, db: Session) -> AvatarProfile:
    profile = db.get(AvatarProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


def _get_owned_look(look_id: UUID, user: User, db: Session) -> Look:
    look = db.get(Look, look_id)
    if look is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look not found")
    profile = db.get(AvatarProfile, look.profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look not found")
    return look


def _to_look_out(look: Look) -> LookOut:
    out = LookOut.model_validate(look)
    out.candidate_urls = [presign_get(k) for k in look.candidate_keys]
    out.approved_url = presign_get(look.approved_key) if look.approved_key else None
    return out


@router.post(
    "/profiles/{profile_id}/looks",
    response_model=LookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_look(
    profile_id: UUID,
    payload: LookCreateRequest,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> LookCreateResponse:
    cached = idempotency.get_cached(db, idempotency_key, LOOKS_IDEMPOTENCY_ENDPOINT)
    if cached is not None:
        return LookCreateResponse.model_validate(cached.body)
    if idempotency_key is not None and not idempotency.claim(
        db, idempotency_key, LOOKS_IDEMPOTENCY_ENDPOINT
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is already in progress.",
        )

    try:
        try:
            moderate(payload.prompt, context="look prompt")
        except ModerationFlagged as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.reason) from exc

        profile = _get_owned_profile(profile_id, user, db)

        if profile.primary_ref_image_key is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This profile has no primary reference image yet. "
                    "Upload and pass a reference video first."
                ),
            )

        garment_url = None
        if payload.garment_asset_id is not None:
            garment_asset = db.get(MediaAsset, payload.garment_asset_id)
            if (
                garment_asset is None
                or garment_asset.profile_id != profile_id
                or garment_asset.kind != "garment"
                or garment_asset.validation != "passed"
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No passing garment asset found with that ID on this profile.",
                )
            garment_url = presign_get(garment_asset.s3_key)

        extra_photos = (
            db.query(MediaAsset)
            .filter(
                MediaAsset.profile_id == profile_id,
                MediaAsset.kind == "photo",
                MediaAsset.validation == "passed",
            )
            .order_by(MediaAsset.created_at.desc())
            .limit(EXTRA_REFERENCE_PHOTOS)
            .all()
        )

        look = Look(
            profile_id=profile_id,
            prompt=payload.prompt,
            garment_asset_id=payload.garment_asset_id,
        )
        db.add(look)
        db.commit()
        db.refresh(look)

        # Fresh random seeds on every call (including a reroll — the frontend just calls
        # this endpoint again with the same prompt) so candidates actually vary;
        # claude.md's M3 reroll mitigation only works if repeats aren't byte-identical.
        seeds = random.sample(range(0, 2**31 - 1), CANDIDATE_COUNT)

        job = jobs_service.enqueue(
            db,
            "look_generation",
            {
                "look_id": str(look.id),
                "profile_id": str(profile_id),
                "prompt": payload.prompt,
                "reference_image_url": presign_get(profile.primary_ref_image_key),
                "extra_reference_image_urls": [presign_get(a.s3_key) for a in extra_photos],
                "garment_image_url": garment_url,
                "output_prefix": f"looks/{look.id}",
                "seeds": seeds,
            },
        )
        result = LookCreateResponse(look_id=look.id, job_id=job.id)
    except Exception:
        if idempotency_key is not None:
            idempotency.release(db, idempotency_key, LOOKS_IDEMPOTENCY_ENDPOINT)
        raise

    if idempotency_key is not None:
        idempotency.store_result(
            db,
            idempotency_key,
            LOOKS_IDEMPOTENCY_ENDPOINT,
            status.HTTP_201_CREATED,
            result.model_dump(mode="json"),
        )
    return result


@router.get("/looks/{look_id}", response_model=LookOut)
def get_look(look_id: UUID, user: CurrentUser, db: DbSession) -> LookOut:
    look = _get_owned_look(look_id, user, db)
    return _to_look_out(look)


@router.post("/looks/{look_id}/approve", response_model=LookOut)
def approve_look(
    look_id: UUID, payload: LookApproveRequest, user: CurrentUser, db: DbSession
) -> LookOut:
    look = _get_owned_look(look_id, user, db)
    if payload.candidate_key not in look.candidate_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That candidate key wasn't one of this look's generated candidates.",
        )
    look.approved_key = payload.candidate_key
    look.status = "approved"
    db.commit()
    db.refresh(look)
    return _to_look_out(look)
