from __future__ import annotations


def _login(client, email: str, password: str) -> dict:
    resp = client.post("/api/admin/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _root_headers(client, admin_user):
    return _login(client, "root", "Admin123!")


def _ops_headers(client, normal_admin):
    return _login(client, "ops@lawbot.local", "OpsPass12")


def test_list_users_requires_role(client, admin_user):
    headers = _root_headers(client, admin_user)
    resp = client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 422


def test_list_users_filtered_by_role(client, admin_user):
    headers = _root_headers(client, admin_user)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "client1@example.com", "password": "secret12"},
    )
    assert reg.status_code == 200

    users = client.get("/api/admin/users", headers=headers, params={"role": "user"})
    assert users.status_code == 200
    assert all(u["role"] == "user" for u in users.json())
    assert any(u["email"] == "client1@example.com" for u in users.json())

    admins = client.get("/api/admin/users", headers=headers, params={"role": "admin"})
    assert admins.status_code == 200
    assert all(u["role"] in ("admin", "super_admin", "operator") for u in admins.json())
    assert any(u["email"] == "root" and u["role"] == "super_admin" for u in admins.json())
    assert all(u.get("created_at") is not None for u in admins.json())


def test_admin_with_manage_can_create_admin(client, admin_user, normal_admin):
    root = _root_headers(client, admin_user)
    created = client.post(
        "/api/admin/users/admins",
        headers=root,
        json={"email": "peer_admin", "password": "PeerPass12", "display_name": "Peer"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admin"

    forbid_root = client.post(
        "/api/admin/users/admins",
        headers=root,
        json={"email": "root", "password": "Whatever1"},
    )
    assert forbid_root.status_code == 400

    # admin role includes admin:manage
    ops = _ops_headers(client, normal_admin)
    created2 = client.post(
        "/api/admin/users/admins",
        headers=ops,
        json={"email": "another_admin", "password": "PeerPass12"},
    )
    assert created2.status_code == 201, created2.text

    login = client.post(
        "/api/admin/auth/login",
        json={"email": "peer_admin", "password": "PeerPass12"},
    )
    assert login.status_code == 200


def test_create_client_by_admin_and_root(client, admin_user, normal_admin):
    ops = _ops_headers(client, normal_admin)
    created = client.post(
        "/api/admin/users/clients",
        headers=ops,
        json={"email": "newuser01@example.com", "password": "secret12", "display_name": "NU"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "user"

    dup = client.post(
        "/api/admin/users/clients",
        headers=ops,
        json={"email": "newuser01@example.com", "password": "secret12"},
    )
    assert dup.status_code == 400

    # C-end login ok; admin login rejected
    user_login = client.post(
        "/api/v1/auth/login",
        json={"email": "newuser01@example.com", "password": "secret12"},
    )
    assert user_login.status_code == 200
    admin_login = client.post(
        "/api/admin/auth/login",
        json={"email": "newuser01@example.com", "password": "secret12"},
    )
    assert admin_login.status_code == 403

    root = _root_headers(client, admin_user)
    created2 = client.post(
        "/api/admin/users/clients",
        headers=root,
        json={"email": "fromroot@example.com", "password": "secret12"},
    )
    assert created2.status_code == 201
    assert created2.json()["display_name"] == "fromroot@example.com"


def test_cannot_disable_root(client, admin_user):
    headers = _root_headers(client, admin_user)
    admins = client.get("/api/admin/users", headers=headers, params={"role": "admin"}).json()
    me = next(u for u in admins if u["email"] == "root")
    resp = client.patch(
        f"/api/admin/users/{me['id']}",
        headers=headers,
        json={"disabled": True},
    )
    assert resp.status_code == 400
    assert "不能禁用超级管理员" in resp.json()["detail"]


def test_normal_admin_cannot_disable_other_admin(client, admin_user, normal_admin):
    root = _root_headers(client, admin_user)
    peer = client.post(
        "/api/admin/users/admins",
        headers=root,
        json={"email": "peer2_admin", "password": "PeerPass12"},
    )
    assert peer.status_code == 201
    peer_id = peer.json()["id"]

    ops = _ops_headers(client, normal_admin)
    denied = client.patch(
        f"/api/admin/users/{peer_id}",
        headers=ops,
        json={"disabled": True},
    )
    assert denied.status_code == 403

    # root can disable normal admin
    ok = client.patch(
        f"/api/admin/users/{peer_id}",
        headers=root,
        json={"disabled": True},
    )
    assert ok.status_code == 200
    assert ok.json()["disabled"] is True


def test_normal_admin_can_disable_end_user(client, normal_admin):
    ops = _ops_headers(client, normal_admin)
    created = client.post(
        "/api/admin/users/clients",
        headers=ops,
        json={"email": "disable_me@example.com", "password": "secret12"},
    )
    assert created.status_code == 201
    target_id = created.json()["id"]
    resp = client.patch(
        f"/api/admin/users/{target_id}",
        headers=ops,
        json={"disabled": True},
    )
    assert resp.status_code == 200
    assert resp.json()["disabled"] is True


def test_cannot_disable_self_when_other_admins_exist(client, admin_user, normal_admin):
    ops = _ops_headers(client, normal_admin)
    admins = client.get("/api/admin/users", headers=ops, params={"role": "admin"}).json()
    me = next(u for u in admins if u["email"] == "ops@lawbot.local")
    # normal admin cannot patch other staff, including self as staff → 403
    resp = client.patch(
        f"/api/admin/users/{me['id']}",
        headers=ops,
        json={"disabled": True},
    )
    assert resp.status_code == 403


def test_admin_me_returns_role(client, admin_user, normal_admin):
    root = _root_headers(client, admin_user)
    me = client.get("/api/admin/auth/me", headers=root)
    assert me.status_code == 200
    assert me.json()["role"] == "super_admin"
    assert me.json()["email"] == "root"

    ops = _ops_headers(client, normal_admin)
    me2 = client.get("/api/admin/auth/me", headers=ops)
    assert me2.status_code == 200
    assert me2.json()["role"] == "admin"


def test_stats_split_counts(client, admin_user):
    headers = _root_headers(client, admin_user)
    client.post(
        "/api/v1/auth/register",
        json={"email": "stat_user@example.com", "password": "secret12"},
    )
    overview = client.get("/api/admin/stats/overview", headers=headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["end_users"] >= 1
    assert body["admins"] >= 1
    assert body["users"] == body["end_users"] + body["admins"]
