from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_admin
from app.services.rbac_out import user_to_out
from app.services.tokens import issue_token_pair, revoke_refresh_token, rotate_refresh_token
from lawbot.db.models import User
from lawbot.domain.schemas import (
    AdminLoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
    UserRole,
    is_staff_role,
)
from lawbot.security import verify_password

router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=TokenResponse)
def admin_login(
    body: AdminLoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.disabled or user.role == UserRole.USER or not is_staff_role(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return issue_token_pair(db, user, settings)


@router.post("/refresh", response_model=TokenResponse)
def admin_refresh(
    body: RefreshRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    return rotate_refresh_token(db, body.refresh_token, settings, require_admin=True)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def admin_logout(
    body: LogoutRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    revoke_refresh_token(db, body.refresh_token, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def admin_me(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    return user_to_out(db, user, with_permissions=True)
