from datetime import UTC, datetime, timedelta

from lawbot.db.models import RefreshToken, User
from lawbot.security import create_access_token, create_refresh_token, hash_password


def _assert_token_response(body: dict) -> None:
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert isinstance(body["expires_in"], int)
    assert body["expires_in"] > 0


def test_register_and_login(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "user01", "password": "secret12", "display_name": "U"},
    )
    assert reg.status_code == 200
    _assert_token_response(reg.json())

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user01", "password": "secret12"},
    )
    assert login.status_code == 200
    _assert_token_response(login.json())
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user01"
    assert me.json()["display_name"] == "U"


def test_register_conflict_message(client):
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "dupuser", "password": "secret12"},
    )
    assert first.status_code == 200
    again = client.post(
        "/api/v1/auth/register",
        json={"email": "dupuser", "password": "secret12"},
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "账号已注册"


def test_register_rejects_invalid_accounts(client):
    for bad in ("ab", "user@example.com", "has space", "Bad-Name", ""):
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": bad, "password": "secret12"},
        )
        assert resp.status_code == 422, bad


def test_register_default_display_name_is_account(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "myuser", "password": "secret12"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["display_name"] == "myuser"
    assert me.json()["email"] == "myuser"


def test_legacy_email_account_can_still_login(client, db_session):
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

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "old@example.com", "password": "secret12"},
    )
    assert login.status_code == 200
    _assert_token_response(login.json())


def test_admin_login(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    _assert_token_response(resp.json())


def test_refresh_rotates_and_revokes_old(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "rotate01", "password": "secret12"},
    )
    old_refresh = reg.json()["refresh_token"]

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


def test_refresh_rejects_access_token_typ(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "typ01", "password": "secret12"},
    )
    access = reg.json()["access_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_refresh_rejects_bad_signature(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "sig01", "password": "secret12"},
    )
    bad = reg.json()["refresh_token"] + "x"
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": bad})
    assert resp.status_code == 401


def test_refresh_rejects_revoked_and_expired(client, db_session):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "expire01", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]
    from jose import jwt

    payload = jwt.get_unverified_claims(refresh)
    jti = payload["jti"]

    row = db_session.get(RefreshToken, jti)
    assert row is not None
    row.revoked_at = datetime.now(UTC)
    db_session.commit()

    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert revoked.status_code == 401

    reg2 = client.post(
        "/api/v1/auth/register",
        json={"email": "expire02", "password": "secret12"},
    )
    refresh2 = reg2.json()["refresh_token"]
    payload2 = jwt.get_unverified_claims(refresh2)
    row2 = db_session.get(RefreshToken, payload2["jti"])
    assert row2 is not None
    row2.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    expired = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh2})
    assert expired.status_code == 401


def test_refresh_rejects_disabled_user(client, db_session):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "disabled01", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]

    user = db_session.query(User).filter_by(email="disabled01").one()
    user.disabled = True
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled01", "password": "secret12"},
    )
    assert login.status_code == 403

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 403


def test_logout_revokes_refresh(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "logout01", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]

    out = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 204

    again = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert again.status_code == 401

    # idempotent
    out2 = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out2.status_code == 204


def test_bearer_refresh_rejected_on_me(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "bearer01", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert me.status_code == 401


def test_admin_refresh_rejects_non_admin(client, admin_user):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "normal01", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]
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
    # sanity on helpers used by issue_token_pair
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


def test_update_profile_display_name(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "profile01", "password": "secret12", "display_name": "Old"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
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


def test_change_password_rejects_wrong_old(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "pwbad01", "password": "secret12"},
    )
    token = reg.json()["access_token"]
    resp = client.post(
        "/api/v1/auth/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "wrong-old", "new_password": "newpass99"},
    )
    assert resp.status_code == 400


def test_change_password_revokes_refresh(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "pwok01", "password": "secret12"},
    )
    access = reg.json()["access_token"]
    refresh = reg.json()["refresh_token"]

    ok = client.post(
        "/api/v1/auth/me/password",
        headers={"Authorization": f"Bearer {access}"},
        json={"old_password": "secret12", "new_password": "newpass99"},
    )
    assert ok.status_code == 204

    revoked = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert revoked.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwok01", "password": "newpass99"},
    )
    assert login.status_code == 200
    _assert_token_response(login.json())
