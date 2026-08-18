from fastapi import APIRouter, HTTPException, status

from app.auth import DbSession, create_access_token
from app.config import settings
from app.db.models import User
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    if payload.email.lower() != settings.founder_email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown user")

    user = db.query(User).filter(User.email == settings.founder_email.lower()).one_or_none()
    if user is None:
        user = User(email=settings.founder_email.lower())
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)
