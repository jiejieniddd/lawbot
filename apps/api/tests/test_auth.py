from datetime import UTC, datetime, timedelta

from lawbot.db.models import RefreshToken, User
from lawbot.security import create_access_token, create_refresh_token, hash_password
from otp_helpers import code_from, login_user, register_user


def _assert_token_response(body: dict) -> None:
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert isinstance(body["expires_in"], int)
    assert body["expires_in"] > 0


def test_register_and_login(client, otp_mail):
    reg = register_user(client, otp_mail, "user01@example.com", display_name="U")
    _assert_token_response(reg)

    login = login_user(client, otp_mail, "user01@example.com", "secret12")
    _assert_token_response(login)
    token = login["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user01@example.com"
    assert me.json()["display_name"] == "U"


def test_register_conflict_message(client, otp_mail):
    register_user(client, otp_mail, "dupuser@example.com")
    again_send = client.post("/api/v1/auth/register/send", json={"email": "dupuser@example.com"})
    assert again_send.status_code == 400
    assert again_send.json()["detail"] == "该邮箱已注册"


def test_register_rejects_invalid_accounts(client, otp_mail):
    for bad in ("ab", "user01", "has space", "Bad-Name", "not-an-email", ""):
        resp = client.post(
            "/api/v1/auth/register/send",
            json={"email": bad},
        )
        assert resp.status_code in (400, 422), bad
    ok = register_user(client, otp_mail, "valid.user@example.com")
    _assert_token_response(ok)


def test_legacy_username_rejected_on_c_end_login(client, db_session, otp_mail):
    db_session.add(
        User(
            email="olduser",
            password_hash=hash_password("secret12"),
            display_name="Old User",
            role="user",
            disabled=False,
        )
    )
    db_session.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"mode": "password", "email": "olduser", "password": "secret12"},
    )
    assert login.status_code == 400
    assert "邮箱" in login.json()["detail"]


def test_register_default_display_name_is_account(client, otp_mail):
    reg = register_user(client, otp_mail, "myuser@example.com")
    token = reg["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["display_name"] == "myuser@example.com"
    assert me.json()["email"] == "myuser@example.com"


def test_legacy_email_account_can_still_login(client, db_session, otp_mail):
    db_session.add(
        User(
            email="old@example.com",
            password_hash=hash_password("secret12"),
            display_name="Old",
            role="user",
            disabled=False,
        )
    )
    db_session.commit()

    login = login_user(client, otp_mail, "old@example.com", "secret12")
    _assert_token_response(login)


def test_admin_login(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    _assert_token_response(resp.json())


def test_refresh_rotates_and_revokes_old(client, otp_mail):
    reg = register_user(client, otp_mail, "rotate01@example.com")
    old_refresh = reg["refresh_token"]

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert refreshed.status_code == 200
    _assert_token_response(refreshed.json())
    new_refresh = refreshed.json()["refresh_token"]
    new_access = refreshed.json()["access_token"]
    assert new_refresh != old_refresh

    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401

    again = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert again.status_code == 200

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200


def test_refresh_rejects_access_token_typ(client, otp_mail):
    reg = register_user(client, otp_mail, "typ01@example.com")
    access = reg["access_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_refresh_rejects_bad_signature(client, otp_mail):
    reg = register_user(client, otp_mail, "sig01@example.com")
    bad = reg["refresh_token"] + "x"
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": bad})
    assert resp.status_code == 401


def test_refresh_rejects_revoked_and_expired(client, db_session, otp_mail):
    reg = register_user(client, otp_mail, "expire01@example.com")
    refresh = reg["refresh_token"]
    from jose import jwt

    payload = jwt.get_unverified_claims(refresh)
    jti = payload["jti"]

    row = db_session.get(RefreshToken, jti)
    assert row is not None
    row.revoked_at = datetime.now(UTC)
    db_session.commit()

    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert revoked.status_code == 401

    reg2 = register_user(client, otp_mail, "expire02@example.com")
    refresh2 = reg2["refresh_token"]
    payload2 = jwt.get_unverified_claims(refresh2)
    row2 = db_session.get(RefreshToken, payload2["jti"])
    assert row2 is not None
    row2.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    expired = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh2})
    assert expired.status_code == 401


def test_refresh_rejects_disabled_user(client, db_session, otp_mail):
    reg = register_user(client, otp_mail, "disabled01@example.com")
    refresh = reg["refresh_token"]

    user = db_session.query(User).filter_by(email="disabled01@example.com").one()
    user.disabled = True
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login/send",
        json={"email": "disabled01@example.com"},
    )
    assert login.status_code == 401

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 403


def test_logout_revokes_refresh(client, otp_mail):
    reg = register_user(client, otp_mail, "logout01@example.com")
    refresh = reg["refresh_token"]

    out = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 204

    again = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert again.status_code == 401

    out2 = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out2.status_code == 204


def test_bearer_refresh_rejected_on_me(client, otp_mail):
    reg = register_user(client, otp_mail, "bearer01@example.com")
    refresh = reg["refresh_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert me.status_code == 401


def test_admin_refresh_rejects_non_admin(client, admin_user, otp_mail):
    reg = register_user(client, otp_mail, "normal01@example.com")
    refresh = reg["refresh_token"]
    resp = client.post("/api/admin/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 403

    admin_login = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    admin_refresh = admin_login.json()["refresh_token"]
    ok = client.post("/api/admin/auth/refresh", json={"refresh_token": admin_refresh})
    assert ok.status_code == 200
    _assert_token_response(ok.json())


def test_create_tokens_include_typ(client):
    access = create_access_token(
        subject="u",
        email="a@b.c",
        role="user",
        secret_key="test-secret",
        expires_minutes=1,
    )
    refresh = create_refresh_token(
        subject="u",
        email="a@b.c",
        role="user",
        jti="jti-1",
        secret_key="test-secret",
        expires_days=1,
    )
    from jose import jwt

    assert jwt.get_unverified_claims(access)["typ"] == "access"
    assert jwt.get_unverified_claims(refresh)["typ"] == "refresh"


def test_update_profile_display_name(client, otp_mail):
    reg = register_user(client, otp_mail, "profile01@example.com", display_name="Old")
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    patched = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"display_name": "新昵称"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "新昵称"
    assert patched.json().get("created_at") is not None

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["display_name"] == "新昵称"
    assert me.json().get("created_at") is not None


def test_change_password_rejects_wrong_old(client, otp_mail):
    reg = register_user(client, otp_mail, "pwbad01@example.com")
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    send = client.post(
        "/api/v1/auth/me/password/send",
        headers=headers,
        json={"old_password": "wrong-old"},
    )
    assert send.status_code == 400
    resp = client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "wrong-old", "new_password": "newpass99", "code": "000000"},
    )
    assert resp.status_code == 400


def test_change_password_requires_code(client, otp_mail):
    reg = register_user(client, otp_mail, "pwcode01@example.com")
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    missing = client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "secret12", "new_password": "newpass99"},
    )
    assert missing.status_code == 422
    bad = client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "secret12", "new_password": "newpass99", "code": "000000"},
    )
    assert bad.status_code == 400


def test_change_password_revokes_refresh(client, otp_mail):
    email = "pwok01@example.com"
    reg = register_user(client, otp_mail, email)
    access = reg["access_token"]
    refresh = reg["refresh_token"]
    headers = {"Authorization": f"Bearer {access}"}

    sent = client.post(
        "/api/v1/auth/me/password/send",
        headers=headers,
        json={"old_password": "secret12"},
    )
    assert sent.status_code == 200, sent.text
    code = code_from(otp_mail, email)

    ok = client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "secret12", "new_password": "newpass99", "code": code},
    )
    assert ok.status_code == 204

    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert revoked.status_code == 401

    login = login_user(client, otp_mail, email, "newpass99")
    _assert_token_response(login)
