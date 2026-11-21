from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.mailer import MailDeliveryError
from lawbot.db.models import AuthChallenge
from otp_helpers import code_from, login_user, login_user_password, register_user, seed_mail_enabled


def test_register_send_and_register_success(client, otp_mail):
    email = "otp-reg@example.com"
    sent = client.post("/api/v1/auth/register/send", json={"email": email})
    assert sent.status_code == 200
    assert sent.json()["detail"] == "验证码已发送"
    assert sent.json()["retry_after_seconds"] == 60
    assert any(c["subject"] == "【律问】注册验证码" for c in otp_mail if c["to"] == email)

    code = code_from(otp_mail, email)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12", "code": code, "display_name": "R"},
    )
    assert reg.status_code == 200
    assert reg.json()["access_token"]


def test_register_wrong_code(client, otp_mail):
    email = "otp-bad@example.com"
    assert client.post("/api/v1/auth/register/send", json={"email": email}).status_code == 200
    bad = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12", "code": "000000"},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "验证码错误"


def test_register_expired_code(client, otp_mail, db_session):
    email = "otp-exp@example.com"
    assert client.post("/api/v1/auth/register/send", json={"email": email}).status_code == 200
    code = code_from(otp_mail, email)
    row = db_session.query(AuthChallenge).filter_by(purpose="register", subject=email).one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    expired = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12", "code": code},
    )
    assert expired.status_code == 400
    assert expired.json()["detail"] == "验证码已过期"


def test_register_challenge_expires_at_is_aware_utc_future(client, otp_mail, db_session):
    """expires_at must remain usable for >1 minute (UTC-safe write)."""
    from app.services.auth_challenges import _as_utc, _now, get_active_challenge

    email = "otp-tz@example.com"
    assert client.post("/api/v1/auth/register/send", json={"email": email}).status_code == 200
    row = db_session.query(AuthChallenge).filter_by(purpose="register", subject=email).one()
    assert _as_utc(row.expires_at) > _now() + timedelta(minutes=1)
    assert get_active_challenge(db_session, "register", email) is not None
    code = code_from(otp_mail, email)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12", "code": code},
    )
    assert reg.status_code == 200


def test_register_send_cooldown(client, otp_mail):
    email = "otp-cool@example.com"
    assert client.post("/api/v1/auth/register/send", json={"email": email}).status_code == 200
    again = client.post("/api/v1/auth/register/send", json={"email": email})
    assert again.status_code == 429
    assert "频繁" in again.json()["detail"]


def test_register_send_already_registered(client, otp_mail):
    register_user(client, otp_mail, "taken@example.com")
    again = client.post("/api/v1/auth/register/send", json={"email": "taken@example.com"})
    assert again.status_code == 400
    assert again.json()["detail"] == "该邮箱已注册"


def test_login_send_unknown_email_does_not_send(client, otp_mail):
    before = len(otp_mail)
    bad = client.post(
        "/api/v1/auth/login/send",
        json={"email": "nobody@example.com"},
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "账号或密码错误"
    assert len(otp_mail) == before


def test_login_email_code_wrong_code(client, otp_mail):
    register_user(client, otp_mail, "login-code@example.com")
    sent = client.post(
        "/api/v1/auth/login/send",
        json={"email": "login-code@example.com"},
    )
    assert sent.status_code == 200
    assert any(c["subject"] == "【律问】登录验证码" for c in otp_mail)
    bad = client.post(
        "/api/v1/auth/login",
        json={"mode": "email_code", "email": "login-code@example.com", "code": "000000"},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "验证码错误"


def test_login_success_with_code(client, otp_mail):
    register_user(client, otp_mail, "login-ok@example.com")
    tokens = login_user(client, otp_mail, "login-ok@example.com", "secret12")
    assert tokens["access_token"]


def test_login_success_with_password_only(client, otp_mail):
    register_user(client, otp_mail, "login-pw-only@example.com")
    tokens = login_user_password(client, "login-pw-only@example.com", "secret12")
    assert tokens["access_token"]


def test_login_password_wrong(client, otp_mail):
    register_user(client, otp_mail, "login-pw-bad@example.com")
    bad = client.post(
        "/api/v1/auth/login",
        json={"mode": "password", "email": "login-pw-bad@example.com", "password": "wrong-pass"},
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "账号或密码错误"


def test_login_missing_mode_422(client, otp_mail):
    register_user(client, otp_mail, "login-mode@example.com")
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "login-mode@example.com", "password": "secret12", "code": "123456"},
    )
    assert resp.status_code == 422


def test_mail_disabled_register_send(client, db_session, monkeypatch, memory_redis):
    seed_mail_enabled(db_session, enabled=False)
    monkeypatch.setattr(
        "app.services.email_otp.send_email",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")),
    )
    resp = client.post("/api/v1/auth/register/send", json={"email": "nomail@example.com"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "邮件服务未启用"


def test_mail_disabled_login_send_password_still_works(client, otp_mail, db_session):
    register_user(client, otp_mail, "mailoff@example.com")
    seed_mail_enabled(db_session, enabled=False)
    resp = client.post(
        "/api/v1/auth/login/send",
        json={"email": "mailoff@example.com"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "邮件服务未启用"
    tokens = login_user_password(client, "mailoff@example.com", "secret12")
    assert tokens["access_token"]


def test_non_email_login_guide(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"mode": "password", "email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 400
    assert "管理员" in resp.json()["detail"]


def test_register_smtp_failure_no_challenge(client, otp_mail, db_session, monkeypatch):
    def boom(config, to, subject, text):
        raise MailDeliveryError("SMTP down")

    monkeypatch.setattr("app.services.email_otp.send_email", boom)
    email = "smtp-fail@example.com"
    resp = client.post("/api/v1/auth/register/send", json={"email": email})
    assert resp.status_code == 502
    assert db_session.query(AuthChallenge).filter_by(purpose="register", subject=email).count() == 0
