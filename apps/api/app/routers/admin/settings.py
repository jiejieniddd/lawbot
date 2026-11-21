from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_permission
from app.services.embedding_config import (
    EmbeddingSettingsUpdate,
    EmbeddingTestBody,
    get_embedding_public,
    save_embedding_config,
    test_embedding_connectivity,
)
from app.services.mail_config import MailSettingsUpdate, get_mail_config, save_mail_config
from app.services.mailer import MailDeliveryError, send_email
from app.services.password_reset import MAIL_DISABLED_MESSAGE, MAIL_INCOMPLETE_MESSAGE
from lawbot.accounts import validate_email_account
from lawbot.db.models import User

router = APIRouter(prefix="/settings", tags=["admin-settings"])


class MailTestBody(BaseModel):
    to: str = ""


@router.get("")
def get_settings_redacted(
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:read")),
) -> dict:
    def mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "****"
        return value[:2] + "****" + value[-2:]

    return {
        "app_env": settings.app_env,
        "database_url": mask(settings.database_url),
        "redis_url": mask(settings.redis_url),
        "llm_source": "db.llm_providers (preferred); env LITELLM_* is legacy optional only",
        "litellm_model": settings.litellm_model or "(unused if providers configured)",
        "litellm_api_key": mask(settings.litellm_api_key),
        "encryption_key_configured": bool(settings.encryption_key),
        "cors_origins": settings.cors_origin_list,
        "access_token_expire_minutes": settings.access_token_expire_minutes,
        "refresh_token_expire_days": settings.refresh_token_expire_days,
    }


@router.get("/mail")
def get_mail_settings(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:read")),
) -> dict:
    return get_mail_config(db, settings).public_dict()


@router.put("/mail")
def update_mail_settings(
    body: MailSettingsUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    try:
        return save_mail_config(db, settings, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/mail/test")
def send_test_mail(
    body: MailTestBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    try:
        to = validate_email_account(body.to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    config = get_mail_config(db, settings)
    if not config.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MAIL_DISABLED_MESSAGE)
    if not config.smtp_host or not config.from_address:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MAIL_INCOMPLETE_MESSAGE)
    if config.password_unreadable:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="邮件发送失败：SMTP 密码无法解密")
    try:
        send_email(config, to, "LawBot 测试邮件", "这是一封系统设置发出的测试邮件。\n")
    except MailDeliveryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"detail": "测试邮件已发送"}


@router.get("/embedding")
def get_embedding_settings(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:read")),
) -> dict:
    return get_embedding_public(db, settings)


@router.put("/embedding")
def update_embedding_settings(
    body: EmbeddingSettingsUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    try:
        return save_embedding_config(db, settings, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/embedding/test")
def test_embedding_settings(
    body: EmbeddingTestBody | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("settings:write")),
) -> dict:
    result = test_embedding_connectivity(db, settings, body)
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(result.get("detail") or "Embedding 测试失败"),
        )
    return result
