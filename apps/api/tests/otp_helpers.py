from __future__ import annotations

import re

import pytest

from app.config import get_settings
from lawbot.crypto import encrypt_secret
from lawbot.db.models import MailSettings

_CODE_RE = re.compile(r"验证码是 (\d{6})")


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expire_at: dict[str, float | None] = {}
        self.now = 0.0

    def _alive(self, key: str) -> bool:
        if key not in self.values:
            return False
        exp = self.expire_at.get(key)
        if exp is not None and self.now >= exp:
            self.values.pop(key, None)
            self.expire_at.pop(key, None)
            return False
        return True

    def set(self, name: str, value: str, ex: int | None = None):
        self.values[name] = str(value)
        self.expire_at[name] = self.now + ex if ex else None
        return True

    def get(self, name: str):
        if not self._alive(name):
            return None
        return self.values[name]

    def delete(self, *names: str) -> int:
        count = 0
        for name in names:
            if name in self.values:
                count += 1
            self.values.pop(name, None)
            self.expire_at.pop(name, None)
        return count

    def ttl(self, name: str) -> int:
        if not self._alive(name):
            return -2
        exp = self.expire_at.get(name)
        if exp is None:
            return -1
        return max(0, int(exp - self.now))


def seed_mail_enabled(db_session, **overrides) -> MailSettings:
    settings = get_settings()
    defaults = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "mailer",
        "smtp_password_encrypted": encrypt_secret(
            "s3cret-mail",
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.secret_key,
        ),
        "from_address": "noreply@example.com",
        "from_name": "CareerBot",
        "code_ttl_minutes": 10,
        "resend_interval_seconds": 60,
    }
    defaults.update(overrides)
    row = db_session.get(MailSettings, 1)
    if row is None:
        row = MailSettings(id=1, **defaults)
        db_session.add(row)
    else:
        for key, value in defaults.items():
            setattr(row, key, value)
        db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def code_from(calls: list[dict], email: str) -> str:
    match = None
    for call in calls:
        if call["to"] == email:
            match = _CODE_RE.search(call["text"])
    assert match, calls
    return match.group(1)


def register_user(
    client,
    otp_mail: list[dict],
    email: str,
    password: str = "secret12",
    display_name: str | None = None,
) -> dict:
    sent = client.post("/api/v1/auth/register/send", json={"email": email})
    assert sent.status_code == 200, sent.text
    code = code_from(otp_mail, email)
    body: dict = {"email": email, "password": password, "code": code}
    if display_name is not None:
        body["display_name"] = display_name
    resp = client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def login_user(client, otp_mail: list[dict], email: str, password: str) -> dict:
    """Login via email OTP (password arg unused for auth; kept for call-site compatibility)."""
    _ = password
    sent = client.post("/api/v1/auth/login/send", json={"email": email})
    assert sent.status_code == 200, sent.text
    code = code_from(otp_mail, email)
    resp = client.post(
        "/api/v1/auth/login",
        json={"mode": "email_code", "email": email, "code": code},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def login_user_password(client, email: str, password: str) -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"mode": "password", "email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def memory_redis(monkeypatch):
    fake = MemoryRedis()
    monkeypatch.setattr("app.services.auth_challenges.get_redis", lambda: fake)
    return fake


@pytest.fixture()
def otp_mail(db_session, monkeypatch, memory_redis):
    seed_mail_enabled(db_session)
    calls: list[dict] = []

    def fake_send(config, to: str, subject: str, text: str) -> None:
        calls.append({"to": to, "subject": subject, "text": text, "config": config})

    monkeypatch.setattr("app.services.email_otp.send_email", fake_send)
    monkeypatch.setattr("app.services.password_reset.send_email", fake_send)
    monkeypatch.setattr("app.routers.admin.settings.send_email", fake_send)
    return calls
