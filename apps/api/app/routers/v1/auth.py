from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_current_user, get_db
from app.services.avatars import delete_avatar_file, save_avatar
from app.services.password_reset import (
    RESET_OK_MESSAGE,
    ResetError,
    reset_password,
    send_reset_code,
)
from app.services.tokens import (
    issue_token_pair,
    revoke_all_refresh_tokens_for_user,
    revoke_refresh_token,
    rotate_refresh_token,
)
from lawbot.accounts import validate_email_account
from lawbot.db.models import User
from lawbot.domain.schemas import (
    LoginRequest,
    LogoutRequest,
    PasswordChange,
    ProfileUpdate,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
    UserRole,
)
from lawbot.rbac.service import ensure_user_has_role, get_role_by_code
from lawbot.security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["v1-auth"])


class ForgotPasswordSendBody(BaseModel):
    email: str = ""


class ForgotPasswordResetBody(BaseModel):
    email: str = ""
    code: str = ""
    new_password: str = Field(default="")


def _email_or_400(value: str) -> str:
    try:
        return validate_email_account(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _raise_reset(exc: ResetError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/forgot-password/send")
def forgot_password_send(
    body: ForgotPasswordSendBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    email = _email_or_400(body.email)
    try:
        return send_reset_code(db, settings, email)
    except ResetError as exc:
        _raise_reset(exc)


@router.post("/forgot-password/reset")
def forgot_password_reset(
    body: ForgotPasswordResetBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    email = _email_or_400(body.email)
    if not 6 <= len(body.new_password) <= 128:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码长度须为 6–128 位")
    try:
        reset_password(db, settings, email, body.code, body.new_password)
    except ResetError as exc:
        _raise_reset(exc)
    return {"detail": RESET_OK_MESSAGE}


@router.post("/register", response_model=TokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已注册")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.email,
        role=UserRole.USER,
    )
    db.add(user)
    db.flush()
    if get_role_by_code(db, UserRole.USER) is not None:
        ensure_user_has_role(db, user, UserRole.USER)
    db.commit()
    db.refresh(user)
    return issue_token_pair(db, user, settings)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    from app.services.auth_challenges import (
        clear_login_failures,
        is_login_locked,
        record_login_failure,
    )

    subject = body.email
    if is_login_locked(db, subject):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请稍后再试",
        )
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        record_login_failure(db, subject)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    clear_login_failures(db, subject)
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


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user.display_name = body.display_name
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid old password")
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    db.flush()
    revoke_all_refresh_tokens_for_user(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    old_url = user.avatar_url
    public_path = await save_avatar(user.id, file, settings)
    user.avatar_url = public_path
    db.add(user)
    db.commit()
    db.refresh(user)
    if old_url and old_url != public_path:
        delete_avatar_file(old_url, settings)
    return user


@router.delete("/me/avatar", response_model=UserOut)
def delete_avatar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    old_url = user.avatar_url
    user.avatar_url = None
    db.add(user)
    db.commit()
    db.refresh(user)
    delete_avatar_file(old_url, settings)
    return user
