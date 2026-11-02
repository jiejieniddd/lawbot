from datetime import UTC, datetime, timedelta

from lawbot.db.models import RefreshToken, User
from lawbot.security import create_access_token, create_refresh_token


def _assert_token_response(body: dict) -> None:
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert isinstance(body["expires_in"], int)
    assert body["expires_in"] > 0


def test_register_and_login(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "secret12", "display_name": "U"},
    )
    assert reg.status_code == 200
    _assert_token_response(reg.json())

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "secret12"},
    )
    assert login.status_code == 200
    _assert_token_response(login.json())
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


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
        json={"email": "rotate@example.com", "password": "secret12"},
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
        json={"email": "typ@example.com", "password": "secret12"},
    )
    access = reg.json()["access_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_refresh_rejects_bad_signature(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "sig@example.com", "password": "secret12"},
    )
    bad = reg.json()["refresh_token"] + "x"
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": bad})
    assert resp.status_code == 401


def test_refresh_rejects_revoked_and_expired(client, db_session):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "expire@example.com", "password": "secret12"},
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
        json={"email": "expire2@example.com", "password": "secret12"},
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
        json={"email": "disabled@example.com", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]

    user = db_session.query(User).filter_by(email="disabled@example.com").one()
    user.disabled = True
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@example.com", "password": "secret12"},
    )
    assert login.status_code == 403

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 403


def test_logout_revokes_refresh(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "logout@example.com", "password": "secret12"},
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
        json={"email": "bearer@example.com", "password": "secret12"},
    )
    refresh = reg.json()["refresh_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert me.status_code == 401


def test_admin_refresh_rejects_non_admin(client, admin_user):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "normal@example.com", "password": "secret12"},
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
