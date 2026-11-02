from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from lawbot.db.models import User
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import UserRole
from lawbot.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_db(settings: Settings = Depends(get_settings)) -> Generator[Session, None, None]:
    factory = get_sessionmaker(settings.database_url)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials, settings.secret_key)
        if payload.typ != "access":
            raise ValueError("invalid token")
        user_id = UUID(payload.sub)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin only")
    return user
