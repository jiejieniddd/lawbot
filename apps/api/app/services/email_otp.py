from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.auth_challenges import (
    PURPOSE_CHANGE_PASSWORD,
    PURPOSE_LOGIN_EMAIL,
    PURPOSE_REGISTER,
    consume_challenge,
    cooldown_active,
    create_challenge,
    get_active_challenge,
    get_latest_challenge,
    purge_expired,
    register_failed_attempt,
)
from app.services.mail_config import MailConfig, get_mail_config
from app.services.mailer import MailDeliveryError, send_email
from lawbot.accounts import normalize_account
from lawbot.db.models import User

logger = logging.getLogger(__name__)

CODE_WRONG_MESSAGE = "验证码错误"
CODE_EXPIRED_MESSAGE = "验证码已过期"
CODE_USED_MESSAGE = "验证码已使用"
CODE_MISSING_MESSAGE = "请重新获取验证码"
# Backward-compatible alias (prefer specific messages above).
INVALID_CODE_MESSAGE = CODE_WRONG_MESSAGE
MAIL_DISABLED_MESSAGE = "邮件服务未启用"
MAIL_INCOMPLETE_MESSAGE = "邮件服务未配置完整"
COOLDOWN_MESSAGE = "发送过于频繁，请稍后再试"
REGISTER_SENT_MESSAGE = "验证码已发送"
LOGIN_SENT_MESSAGE = "验证码已发送"
CHANGE_PASSWORD_SENT_MESSAGE = "验证码已发送"
EMAIL_ALREADY_REGISTERED_MESSAGE = "该邮箱已注册"
MAX_ATTEMPTS = 5


class OtpError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# Backward-compatible alias for password_reset / admin settings imports.
ResetError = OtpError


def digest_code(secret: str, email: str, code: str) -> str:
    subject = normalize_account(email)
    payload = f"{subject}:{code}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def ensure_mail_ready(config: MailConfig) -> None:
    if not config.enabled:
        raise OtpError(400, MAIL_DISABLED_MESSAGE)
    if not config.smtp_host or not config.from_address:
        raise OtpError(400, MAIL_INCOMPLETE_MESSAGE)
    if config.password_unreadable:
        raise OtpError(502, "邮件发送失败：SMTP 密码无法解密")


def _sent_payload(detail: str, config: MailConfig) -> dict:
    return {
        "detail": detail,
        "retry_after_seconds": config.resend_interval_seconds,
    }


def _purge_best_effort(db: Session) -> None:
    try:
        purge_expired(db)
    except Exception:
        logger.exception("purge_expired during email otp send failed")


def _subject_log_tag(email: str) -> str:
    return hashlib.sha256(normalize_account(email).encode()).hexdigest()[:12]


def _issue_code_email(
    db: Session,
    settings: Settings,
    *,
    purpose: str,
    email: str,
    mail_subject: str,
    sent_detail: str,
) -> dict:
    email = normalize_account(email)
    config = get_mail_config(db, settings)
    ensure_mail_ready(config)
    _purge_best_effort(db)

    if cooldown_active(db, purpose, email, config.resend_interval_seconds):
        raise OtpError(429, COOLDOWN_MESSAGE)

    cooldown_ttl = max(config.resend_interval_seconds, 60)
    minutes = config.code_ttl_minutes
    code = f"{secrets.randbelow(1_000_000):06d}"
    text = f"你的验证码是 {code}，{minutes} 分钟内有效。\n如果不是你本人操作，请忽略这封邮件。\n"
    try:
        send_email(config, email, mail_subject, text)
    except MailDeliveryError as exc:
        raise OtpError(502, str(exc)) from exc

    create_challenge(
        db,
        purpose=purpose,
        subject=email,
        code_hash=digest_code(settings.secret_key, email, code),
        ttl_seconds=max(minutes * 60, cooldown_ttl),
        max_attempts=MAX_ATTEMPTS,
    )
    return _sent_payload(sent_detail, config)


def send_register_code(db: Session, settings: Settings, email: str) -> dict:
    email = normalize_account(email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise OtpError(400, EMAIL_ALREADY_REGISTERED_MESSAGE)
    return _issue_code_email(
        db,
        settings,
        purpose=PURPOSE_REGISTER,
        email=email,
        mail_subject="【律问】注册验证码",
        sent_detail=REGISTER_SENT_MESSAGE,
    )


def send_login_code(db: Session, settings: Settings, email: str) -> dict:
    """Caller must have already verified the account is usable."""
    return _issue_code_email(
        db,
        settings,
        purpose=PURPOSE_LOGIN_EMAIL,
        email=normalize_account(email),
        mail_subject="【律问】登录验证码",
        sent_detail=LOGIN_SENT_MESSAGE,
    )


def send_change_password_code(db: Session, settings: Settings, email: str) -> dict:
    """Caller must have verified the current password for the logged-in user."""
    return _issue_code_email(
        db,
        settings,
        purpose=PURPOSE_CHANGE_PASSWORD,
        email=normalize_account(email),
        mail_subject="【律问】修改密码验证码",
        sent_detail=CHANGE_PASSWORD_SENT_MESSAGE,
    )


def verify_and_consume(db: Session, settings: Settings, purpose: str, email: str, code: str) -> None:
    email = normalize_account(email)
    tag = _subject_log_tag(email)
    challenge = get_active_challenge(db, purpose, email)
    if challenge is None:
        latest = get_latest_challenge(db, purpose, email)
        if latest is None:
            logger.info("otp_verify missing purpose=%s subject=%s", purpose, tag)
            raise OtpError(400, CODE_MISSING_MESSAGE)
        if latest.used_at is not None:
            logger.info("otp_verify used purpose=%s subject=%s", purpose, tag)
            raise OtpError(400, CODE_USED_MESSAGE)
        if latest.is_expired():
            logger.info("otp_verify expired purpose=%s subject=%s", purpose, tag)
            raise OtpError(400, CODE_EXPIRED_MESSAGE)
        logger.info("otp_verify inactive purpose=%s subject=%s", purpose, tag)
        raise OtpError(400, CODE_MISSING_MESSAGE)

    if not challenge.code_hash:
        logger.info("otp_verify no_hash purpose=%s subject=%s", purpose, tag)
        raise OtpError(400, CODE_MISSING_MESSAGE)

    expected = digest_code(settings.secret_key, email, code.strip())
    if not hmac.compare_digest(challenge.code_hash, expected):
        register_failed_attempt(db, challenge)
        logger.info("otp_verify wrong_code purpose=%s subject=%s", purpose, tag)
        raise OtpError(400, CODE_WRONG_MESSAGE)

    consumed = consume_challenge(db, challenge.id)
    if consumed is None:
        logger.info("otp_verify consume_failed purpose=%s subject=%s", purpose, tag)
        raise OtpError(400, CODE_USED_MESSAGE)
