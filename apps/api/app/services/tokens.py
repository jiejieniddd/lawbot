from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import Settings
from lawbot.db.models import RefreshToken, User
from lawbot.domain.schemas import TokenResponse, UserRole
from lawbot.security import (
    TOKEN_TYP_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
)


def issue_token_pair(db: Session, user: User, settings: Settings) -> TokenResponse:
    jti = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    access = create_access_token(
        subject=str(user.id),
        email=user.email,
        role=user.role,
        secret_key=settings.secret_key,
        expires_minutes=settings.access_token_expire_minutes,
    )
    refresh = create_refresh_token(
        subject=str(user.id),
        email=user.email,
        role=user.role,
        jti=jti,
        secret_key=settings.secret_key,
        expires_days=settings.refresh_token_expire_days,
    )
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


def rotate_refresh_token(
    db: Session,
    refresh_token: str,
    settings: Settings,
    *,
    require_admin: bool = False,
) -> TokenResponse:
    try:
        payload = decode_token(refresh_token, settings.secret_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.typ != TOKEN_TYP_REFRESH or not payload.jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    row = db.get(RefreshToken, payload.jti)
    if row is None or row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    now = datetime.now(UTC)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    if require_admin and user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

    row.revoked_at = now
    db.add(row)
    db.flush()
    return issue_token_pair(db, user, settings)


def revoke_refresh_token(db: Session, refresh_token: str, settings: Settings) -> None:
    try:
        payload = decode_token(refresh_token, settings.secret_key)
    except ValueError:
        return

    if payload.typ != TOKEN_TYP_REFRESH or not payload.jti:
        return

    row = db.get(RefreshToken, payload.jti)
    if row is None or row.revoked_at is not None:
        return

    row.revoked_at = datetime.now(UTC)
    db.add(row)
    db.commit()
