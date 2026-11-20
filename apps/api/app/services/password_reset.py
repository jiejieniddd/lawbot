from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.auth_challenges import (
    PURPOSE_RESET_PASSWORD,
    consume_challenge,
    cooldown_active,
    create_challenge,
    get_active_challenge,
    purge_expired,
    register_failed_attempt,
)
from app.services.mail_config import MailConfig, get_mail_config
from app.services.mailer import MailDeliveryError, send_email
from app.services.tokens import revoke_all_refresh_tokens_for_user
from lawbot.db.models import User
from lawbot.security import hash_password

logger = logging.getLogger(__name__)

RESET_SENT_MESSAGE = "若该邮箱已注册，验证码已发送"
RESET_OK_MESSAGE = "密码已重置，请重新登录"
INVALID_CODE_MESSAGE = "验证码无效或已过期"
MAIL_DISABLED_MESSAGE = "邮件服务未启用"
MAIL_INCOMPLETE_MESSAGE = "邮件服务未配置完整"
COOLDOWN_MESSAGE = "发送过于频繁，请稍后再试"
MAX_ATTEMPTS = 5


class ResetError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _digest(secret: str, email: str, code: str) -> str:
    payload = f"{email}:{code}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _sent(config: MailConfig) -> dict:
    return {
        "detail": RESET_SENT_MESSAGE,
        "retry_after_seconds": config.resend_interval_seconds,
    }


def _ensure_ready(config: MailConfig) -> None:
    if not config.enabled:
        raise ResetError(400, MAIL_DISABLED_MESSAGE)
    if not config.smtp_host or not config.from_address:
        raise ResetError(400, MAIL_INCOMPLETE_MESSAGE)
    if config.password_unreadable:
        raise ResetError(502, "邮件发送失败：SMTP 密码无法解密")


def send_reset_code(db: Session, settings: Settings, email: str) -> dict:
    config = get_mail_config(db, settings)
    _ensure_ready(config)
    try:
        purge_expired(db)
    except Exception:
        logger.exception("purge_expired during send_reset_code failed")

    if cooldown_active(db, PURPOSE_RESET_PASSWORD, email, config.resend_interval_seconds):
        raise ResetError(429, COOLDOWN_MESSAGE)

    user = db.scalar(select(User).where(User.email == email))
    # Cooldown TTL at least resend interval so Postgres created_at enforces spacing
    cooldown_ttl = max(config.resend_interval_seconds, 60)

    if user is None or user.disabled:
        # Same success response; no usable code (mark_used, null hash)
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
        code_hash=_digest(settings.secret_key, email, code),
        ttl_seconds=max(minutes * 60, cooldown_ttl),
        max_attempts=MAX_ATTEMPTS,
    )
    return _sent(config)


def reset_password(db: Session, settings: Settings, email: str, code: str, new_password: str) -> None:
    challenge = get_active_challenge(db, PURPOSE_RESET_PASSWORD, email)
    if challenge is None or not challenge.code_hash:
        raise ResetError(400, INVALID_CODE_MESSAGE)

    expected = _digest(settings.secret_key, email, code.strip())
    if not hmac.compare_digest(challenge.code_hash, expected):
        register_failed_attempt(db, challenge)
        raise ResetError(400, INVALID_CODE_MESSAGE)

    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.disabled:
        raise ResetError(400, INVALID_CODE_MESSAGE)

    consumed = consume_challenge(db, challenge.id)
    if consumed is None:
        raise ResetError(400, INVALID_CODE_MESSAGE)

    # Re-load user after consume commit (new transaction boundary)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.disabled:
        raise ResetError(400, INVALID_CODE_MESSAGE)
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.flush()
    revoke_all_refresh_tokens_for_user(db, user.id)
