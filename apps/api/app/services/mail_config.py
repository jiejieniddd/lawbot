from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings
from lawbot.crypto import decrypt_secret, encrypt_secret
from lawbot.db.models import MailSettings

SINGLETON_ID = 1
SECURITY_VALUES = {"none", "starttls", "ssl"}


class MailSettingsUpdate(BaseModel):
    enabled: bool
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: str = "starttls"
    smtp_username: str = Field(default="", max_length=255)
    smtp_password: str = Field(default="", max_length=255)
    from_address: str = Field(default="", max_length=255)
    from_name: str = Field(default="LawBot", max_length=120)
    code_ttl_minutes: int = Field(default=10, ge=1, le=60)
    resend_interval_seconds: int = Field(default=60, ge=30, le=3600)


class MailConfig:
    def __init__(
        self,
        *,
        enabled: bool,
        smtp_host: str,
        smtp_port: int,
        smtp_security: str,
        smtp_username: str,
        smtp_password: str,
        from_address: str,
        from_name: str,
        code_ttl_minutes: int,
        resend_interval_seconds: int,
        password_configured: bool,
    ) -> None:
        self.enabled = enabled
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_security = smtp_security
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.from_name = from_name
        self.code_ttl_minutes = code_ttl_minutes
        self.resend_interval_seconds = resend_interval_seconds
        self.password_configured = password_configured
        self.password_unreadable = False

    def public_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_security": self.smtp_security,
            "smtp_username": self.smtp_username,
            "password_configured": self.password_configured,
            "from_address": self.from_address,
            "from_name": self.from_name,
            "code_ttl_minutes": self.code_ttl_minutes,
            "resend_interval_seconds": self.resend_interval_seconds,
        }


def _crypto_kwargs(settings: Settings) -> dict:
    return {
        "encryption_key": settings.encryption_key or None,
        "jwt_secret": settings.secret_key,
    }


def _encrypt(plaintext: str, settings: Settings) -> str:
    if not plaintext:
        return ""
    return encrypt_secret(plaintext, **_crypto_kwargs(settings))


def _decrypt(ciphertext: str, settings: Settings) -> str:
    if not ciphertext:
        return ""
    return decrypt_secret(ciphertext, **_crypto_kwargs(settings))


def _security(value: str) -> str:
    return value if value in SECURITY_VALUES else "starttls"


def _from_env(settings: Settings) -> MailConfig:
    password = settings.smtp_password or ""
    return MailConfig(
        enabled=bool(settings.mail_enabled),
        smtp_host=(settings.smtp_host or "").strip(),
        smtp_port=int(settings.smtp_port or 587),
        smtp_security=_security(settings.smtp_security or "starttls"),
        smtp_username=settings.smtp_username or "",
        smtp_password=password,
        from_address=(settings.smtp_from_address or "").strip(),
        from_name=settings.smtp_from_name or "LawBot",
        code_ttl_minutes=max(1, int(settings.password_reset_ttl_minutes or 10)),
        resend_interval_seconds=max(1, int(settings.password_reset_resend_seconds or 60)),
        password_configured=bool(password),
    )


def _from_row(row: MailSettings, settings: Settings) -> MailConfig:
    ciphertext = row.smtp_password_encrypted or ""
    password = ""
    unreadable = False
    if ciphertext:
        try:
            password = _decrypt(ciphertext, settings)
        except ValueError:
            unreadable = True
    config = MailConfig(
        enabled=bool(row.enabled),
        smtp_host=(row.smtp_host or "").strip(),
        smtp_port=int(row.smtp_port or 587),
        smtp_security=_security(row.smtp_security or "starttls"),
        smtp_username=row.smtp_username or "",
        smtp_password=password,
        from_address=(row.from_address or "").strip(),
        from_name=row.from_name or "LawBot",
        code_ttl_minutes=max(1, int(row.code_ttl_minutes or 10)),
        resend_interval_seconds=max(1, int(row.resend_interval_seconds or 60)),
        password_configured=bool(ciphertext),
    )
    config.password_unreadable = unreadable
    return config


def get_mail_config(db: Session, settings: Settings) -> MailConfig:
    row = db.get(MailSettings, SINGLETON_ID)
    if row is None:
        return _from_env(settings)
    return _from_row(row, settings)


def save_mail_config(db: Session, settings: Settings, body: MailSettingsUpdate) -> dict:
    if body.smtp_security not in SECURITY_VALUES:
        raise ValueError("SMTP 安全方式无效")
    row = db.get(MailSettings, SINGLETON_ID)
    if row is None:
        row = MailSettings(id=SINGLETON_ID)
        stored_password = _encrypt(settings.smtp_password or "", settings)
        db.add(row)
    else:
        stored_password = row.smtp_password_encrypted or ""
    if body.smtp_password:
        stored_password = _encrypt(body.smtp_password, settings)
    row.enabled = body.enabled
    row.smtp_host = body.smtp_host.strip()
    row.smtp_port = body.smtp_port
    row.smtp_security = body.smtp_security
    row.smtp_username = body.smtp_username.strip()
    row.smtp_password_encrypted = stored_password
    row.from_address = body.from_address.strip()
    row.from_name = body.from_name.strip() or "LawBot"
    row.code_ttl_minutes = body.code_ttl_minutes
    row.resend_interval_seconds = body.resend_interval_seconds
    db.add(row)
    db.commit()
    db.refresh(row)
    return _from_row(row, settings).public_dict()
