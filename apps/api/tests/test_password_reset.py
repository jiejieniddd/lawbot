from __future__ import annotations

import re

import pytest

from app.config import get_settings
from app.services.mailer import MailDeliveryError
from lawbot.crypto import decrypt_secret
from lawbot.db.models import MailSettings, User

SENT_MESSAGE = "若该邮箱已注册，验证码已发送"
INVALID_CODE = "验证码无效或已过期"
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


@pytest.fixture()
def memory_redis(monkeypatch):
    fake = MemoryRedis()
    monkeypatch.setattr("app.services.auth_challenges.get_redis", lambda: fake)
    return fake


@pytest.fixture()
def sent_mail(monkeypatch):
    calls: list[dict] = []

    def fake_send(config, to: str, subject: str, text: str) -> None:
        calls.append({"to": to, "subject": subject, "text": text, "config": config})

    monkeypatch.setattr("app.services.password_reset.send_email", fake_send)
    monkeypatch.setattr("app.routers.admin.settings.send_email", fake_send)
    return calls


def _root_headers(client, admin_user):
    resp = client.post("/api/admin/auth/login", json={"email": "root", "password": "Admin123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _ops_headers(client, normal_admin):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "ops@lawbot.local", "password": "OpsPass12"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _mail_body(**overrides):
    body = {
        "enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "mailer",
        "smtp_password": "s3cret-mail",
        "from_address": "noreply@example.com",
        "from_name": "LawBot",
        "code_ttl_minutes": 10,
        "resend_interval_seconds": 60,
    }
    body.update(overrides)
    return body


def _enable_mail(client, headers, **overrides):
    resp = client.put("/api/admin/settings/mail", headers=headers, json=_mail_body(**overrides))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _register(client, email: str = "reset-user@example.com"):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _send(client, email: str):
    return client.post("/api/v1/auth/forgot-password/send", json={"email": email})


def _reset(client, email: str, code: str, password: str = "newpass99"):
    return client.post(
        "/api/v1/auth/forgot-password/reset",
        json={"email": email, "code": code, "new_password": password},
    )


def _code_from(calls: list[dict], email: str) -> str:
    match = None
    for call in calls:
        if call["to"] == email:
            match = _CODE_RE.search(call["text"])
    assert match, calls
    return match.group(1)


def test_reset_with_valid_code_and_revoke_refresh(client, admin_user, memory_redis, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    registered = _register(client)
    email = "reset-user@example.com"
    refresh = registered["refresh_token"]

    sent = _send(client, email)
    assert sent.status_code == 200, sent.text
    assert sent.json()["detail"] == SENT_MESSAGE
    code = _code_from(sent_mail, email)

    short = _reset(client, email, code, "123")
    assert short.status_code == 400
    assert "密码" in short.json()["detail"]

    reset = _reset(client, email, code, "newpass99")
    assert reset.status_code == 200, reset.text
    assert reset.json()["detail"] == "密码已重置，请重新登录"

    old = client.post("/api/v1/auth/login", json={"email": email, "password": "secret12"})
    assert old.status_code == 401
    new = client.post("/api/v1/auth/login", json={"email": email, "password": "newpass99"})
    assert new.status_code == 200
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert reused.status_code == 401


def test_wrong_code_then_too_many_attempts(client, admin_user, memory_redis, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "attempts@example.com"
    _register(client, email)
    sent = _send(client, email)
    assert sent.status_code == 200
    code = _code_from(sent_mail, email)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        resp = _reset(client, email, wrong)
        assert resp.status_code == 400
        assert resp.json()["detail"] == INVALID_CODE
    burned = _reset(client, email, code)
    assert burned.status_code == 400
    assert burned.json()["detail"] == INVALID_CODE
    still = client.post("/api/v1/auth/login", json={"email": email, "password": "secret12"})
    assert still.status_code == 200


def test_expired_code(client, admin_user, db_session, memory_redis, sent_mail):
    from datetime import UTC, datetime, timedelta

    from lawbot.db.models import AuthChallenge

    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "expired@example.com"
    _register(client, email)
    assert _send(client, email).status_code == 200
    code = _code_from(sent_mail, email)
    row = (
        db_session.query(AuthChallenge)
        .filter_by(purpose="reset_password", subject=email)
        .order_by(AuthChallenge.created_at.desc())
        .one()
    )
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    memory_redis.values.clear()
    resp = _reset(client, email, code)
    assert resp.status_code == 400
    assert resp.json()["detail"] == INVALID_CODE


def test_code_cannot_be_reused(client, admin_user, memory_redis, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "once@example.com"
    _register(client, email)
    assert _send(client, email).status_code == 200
    code = _code_from(sent_mail, email)
    assert _reset(client, email, code).status_code == 200
    again = _reset(client, email, code, "otherpass1")
    assert again.status_code == 400
    assert again.json()["detail"] == INVALID_CODE


def test_unknown_email_matches_registered_response(client, admin_user, memory_redis, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    known = "known@example.com"
    _register(client, known)
    missing = _send(client, "missing@example.com")
    found = _send(client, known)
    assert missing.status_code == 200
    assert found.status_code == 200
    assert missing.json() == found.json()
    assert missing.json()["detail"] == SENT_MESSAGE
    assert [call["to"] for call in sent_mail] == [known]


def test_disabled_user_does_not_send(client, admin_user, db_session, memory_redis, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "disabled-reset@example.com"
    _register(client, email)
    user = db_session.query(User).filter_by(email=email).one()
    user.disabled = True
    db_session.commit()

    disabled = _send(client, email)
    missing = _send(client, "nobody-disabled@example.com")
    assert disabled.status_code == 200
    assert disabled.json() == missing.json()
    assert sent_mail == []


def test_mail_disabled_returns_explicit_error(client, memory_redis, sent_mail):
    resp = _send(client, "someone@example.com")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "邮件服务未启用"
    assert sent_mail == []


def test_smtp_failure_does_not_pretend_sent(client, admin_user, memory_redis, monkeypatch):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "smtp-fail@example.com"
    _register(client, email)

    def boom(config, to, subject, text):
        raise MailDeliveryError("邮件发送失败：connection refused")

    monkeypatch.setattr("app.services.password_reset.send_email", boom)
    resp = _send(client, email)
    assert resp.status_code == 502
    assert "邮件发送失败" in resp.json()["detail"]
    assert not any(key.startswith("lawbot:auth:challenge:") for key in memory_redis.values)


def test_mail_settings_roundtrip_hides_password(client, admin_user, normal_admin, db_session):
    root = _root_headers(client, admin_user)
    saved = _enable_mail(client, root)
    assert saved["password_configured"] is True
    assert "s3cret-mail" not in str(saved)
    assert "smtp_password" not in saved

    again = client.get("/api/admin/settings/mail", headers=root)
    assert again.status_code == 200
    assert again.json()["smtp_host"] == "smtp.example.com"
    assert again.json()["password_configured"] is True
    assert "s3cret-mail" not in again.text

    updated = _enable_mail(client, root, smtp_password="", smtp_host="smtp.other.example")
    assert updated["smtp_host"] == "smtp.other.example"
    assert updated["password_configured"] is True
    assert "s3cret-mail" not in str(updated)

    db_session.expire_all()
    row = db_session.get(MailSettings, 1)
    assert row is not None
    assert row.smtp_password_encrypted != "s3cret-mail"
    settings = get_settings()
    plain = decrypt_secret(
        row.smtp_password_encrypted,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    assert plain == "s3cret-mail"

    ops = _ops_headers(client, normal_admin)
    denied = client.put(
        "/api/admin/settings/mail",
        headers=ops,
        json=_mail_body(smtp_password=""),
    )
    assert denied.status_code == 403
    readable = client.get("/api/admin/settings/mail", headers=ops)
    assert readable.status_code == 200


def test_admin_test_mail_uses_saved_config(client, admin_user, sent_mail):
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    resp = client.post(
        "/api/admin/settings/mail/test",
        headers=headers,
        json={"to": "qa@example.com"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == "测试邮件已发送"
    assert sent_mail[0]["to"] == "qa@example.com"
    assert sent_mail[0]["config"].smtp_password == "s3cret-mail"


def test_reset_after_redis_key_deleted(client, admin_user, memory_redis, sent_mail):
    """Postgres remains source of truth when Redis cache is wiped."""
    from app.services.auth_challenges import PURPOSE_RESET_PASSWORD, redis_key

    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "redis-miss@example.com"
    _register(client, email)
    assert _send(client, email).status_code == 200
    code = _code_from(sent_mail, email)
    key = redis_key(PURPOSE_RESET_PASSWORD, email)
    assert key in memory_redis.values
    memory_redis.delete(key)
    reset = _reset(client, email, code, "newpass99")
    assert reset.status_code == 200, reset.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "newpass99"})
    assert login.status_code == 200


def test_send_and_reset_when_redis_down(client, admin_user, sent_mail, monkeypatch):
    class BoomRedis:
        def set(self, *a, **k):
            raise ConnectionError("redis down")

        def get(self, *a, **k):
            raise ConnectionError("redis down")

        def delete(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.services.auth_challenges.get_redis", lambda: BoomRedis())
    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "redis-down@example.com"
    _register(client, email)
    sent = _send(client, email)
    assert sent.status_code == 200, sent.text
    code = _code_from(sent_mail, email)
    reset = _reset(client, email, code, "newpass99")
    assert reset.status_code == 200, reset.text


def test_unknown_email_leaves_no_usable_code(client, admin_user, db_session, memory_redis, sent_mail):
    from lawbot.db.models import AuthChallenge

    headers = _root_headers(client, admin_user)
    _enable_mail(client, headers)
    email = "ghost@example.com"
    resp = _send(client, email)
    assert resp.status_code == 200
    assert sent_mail == []
    rows = db_session.query(AuthChallenge).filter_by(purpose="reset_password", subject=email).all()
    assert len(rows) == 1
    assert rows[0].code_hash is None
    assert rows[0].used_at is not None
    assert _reset(client, email, "123456").status_code == 400


def test_login_lockout_after_failures(client, memory_redis):
    email = "lockout@example.com"
    _register(client, email)
    for _ in range(5):
        bad = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass"})
        assert bad.status_code == 401
    locked = client.post("/api/v1/auth/login", json={"email": email, "password": "secret12"})
    assert locked.status_code == 429
    assert "登录失败" in locked.json()["detail"]
