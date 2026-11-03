from __future__ import annotations

from collections.abc import Callable, Generator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from lawbot.db.models import User
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import UserRole, is_staff_role, is_super_admin_role
from lawbot.rbac.service import user_has_permission, user_is_staff
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
    if not user_is_staff(user) and not is_staff_role(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    if user.role == UserRole.USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not is_super_admin_role(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin only")
    return user


def require_permission(code: str) -> Callable[..., User]:
    def _dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user.role == UserRole.USER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
        if not user_has_permission(db, user, code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return user

    return _dep
