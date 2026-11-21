from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.auth_challenges import (
    PURPOSE_RESET_PASSWORD,
    cooldown_active,
    create_challenge,
    purge_expired,
)
from app.services.email_otp import (
    CODE_WRONG_MESSAGE,
    COOLDOWN_MESSAGE,
    INVALID_CODE_MESSAGE,
    MAIL_DISABLED_MESSAGE,
    MAIL_INCOMPLETE_MESSAGE,
    MAX_ATTEMPTS,
    OtpError,
    digest_code,
    ensure_mail_ready,
    verify_and_consume,
)
from app.services.mail_config import get_mail_config
from app.services.mailer import MailDeliveryError, send_email
from app.services.tokens import revoke_all_refresh_tokens_for_user
from lawbot.db.models import User
from lawbot.security import hash_password

logger = logging.getLogger(__name__)

RESET_SENT_MESSAGE = "若该邮箱已注册，验证码已发送"
RESET_OK_MESSAGE = "密码已重置，请重新登录"

# Re-export for admin settings / routers
ResetError = OtpError

__all__ = [
    "COOLDOWN_MESSAGE",
    "INVALID_CODE_MESSAGE",
    "MAIL_DISABLED_MESSAGE",
    "MAIL_INCOMPLETE_MESSAGE",
    "RESET_OK_MESSAGE",
    "RESET_SENT_MESSAGE",
    "ResetError",
    "reset_password",
    "send_reset_code",
]


def _sent(config) -> dict:
    return {
        "detail": RESET_SENT_MESSAGE,
        "retry_after_seconds": config.resend_interval_seconds,
    }


def send_reset_code(db: Session, settings: Settings, email: str) -> dict:
    config = get_mail_config(db, settings)
    ensure_mail_ready(config)
    try:
        purge_expired(db)
    except Exception:
        logger.exception("purge_expired during send_reset_code failed")

    if cooldown_active(db, PURPOSE_RESET_PASSWORD, email, config.resend_interval_seconds):
        raise ResetError(429, COOLDOWN_MESSAGE)

    user = db.scalar(select(User).where(User.email == email))
    cooldown_ttl = max(config.resend_interval_seconds, 60)

    if user is None or user.disabled:
        create_challenge(
            db,
            purpose=PURPOSE_RESET_PASSWORD,
            subject=email,
            code_hash=None,
            ttl_seconds=cooldown_ttl,
            max_attempts=0,
            mark_used=True,
        )
        return _sent(config)

    code = f"{secrets.randbelow(1_000_000):06d}"
    minutes = config.code_ttl_minutes
    subject = "LawBot 密码重置验证码"
    text = f"你的验证码是 {code}，{minutes} 分钟内有效。\n如果不是你本人操作，请忽略这封邮件。\n"
    try:
        send_email(config, email, subject, text)
    except MailDeliveryError as exc:
        raise ResetError(502, str(exc)) from exc

    create_challenge(
        db,
        purpose=PURPOSE_RESET_PASSWORD,
        subject=email,
        code_hash=digest_code(settings.secret_key, email, code),
        ttl_seconds=max(minutes * 60, cooldown_ttl),
        max_attempts=MAX_ATTEMPTS,
    )
    return _sent(config)


def reset_password(db: Session, settings: Settings, email: str, code: str, new_password: str) -> None:
    verify_and_consume(db, settings, PURPOSE_RESET_PASSWORD, email, code)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.disabled:
        raise ResetError(400, CODE_WRONG_MESSAGE)
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.flush()
    revoke_all_refresh_tokens_for_user(db, user.id)
