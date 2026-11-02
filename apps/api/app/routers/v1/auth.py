from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_current_user, get_db
from app.services.tokens import issue_token_pair, revoke_refresh_token, rotate_refresh_token
from lawbot.db.models import User
from lawbot.domain.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    UserRole,
)
from lawbot.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["v1-auth"])


@router.post("/register", response_model=TokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    existing = db.scalar(select(User).where(User.email == body.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.email.split("@")[0],
        role=UserRole.USER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return issue_token_pair(db, user, settings)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    return issue_token_pair(db, user, settings)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    return rotate_refresh_token(db, body.refresh_token, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: LogoutRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    revoke_refresh_token(db, body.refresh_token, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
