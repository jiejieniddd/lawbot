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


def test_list_users_filtered_by_role(client, admin_user, otp_mail):
    from otp_helpers import register_user

    headers = _root_headers(client, admin_user)
    register_user(client, otp_mail, "client1@example.com")

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


def test_create_client_by_admin_and_root(client, admin_user, normal_admin, otp_mail):
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
    from otp_helpers import login_user

    user_login = login_user(client, otp_mail, "newuser01@example.com", "secret12")
    assert user_login["access_token"]
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


def test_stats_split_counts(client, admin_user, otp_mail):
    from otp_helpers import register_user

    headers = _root_headers(client, admin_user)
    register_user(client, otp_mail, "stat_user@example.com")
    overview = client.get("/api/admin/stats/overview", headers=headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["end_users"] >= 1
    assert body["admins"] >= 1
    assert body["users"] == body["end_users"] + body["admins"]


def test_hard_delete_client_cascades_conversations(client, admin_user, db_session):
    from uuid import UUID

    from sqlalchemy import func, select

    from lawbot.db.models import Conversation, Message, User
    from lawbot.domain.schemas import MessageRole

    root = _root_headers(client, admin_user)
    created = client.post(
        "/api/admin/users/clients",
        headers=root,
        json={"email": "wipe_me@example.com", "password": "secret12", "display_name": "Wipe"},
    )
    assert created.status_code == 201, created.text
    target_id = UUID(created.json()["id"])

    conv = Conversation(user_id=target_id, title="待删会话")
    db_session.add(conv)
    db_session.flush()
    db_session.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content="hello",
            citations=[],
        )
    )
    db_session.commit()
    conv_id = conv.id

    deleted = client.delete(f"/api/admin/users/{target_id}", headers=root)
    assert deleted.status_code == 204, deleted.text

    listed = client.get("/api/admin/users", headers=root, params={"role": "user"})
    assert listed.status_code == 200
    assert all(u["id"] != str(target_id) for u in listed.json())
    db_session.expire_all()
    assert db_session.get(User, target_id) is None
    assert db_session.get(Conversation, conv_id) is None
    left = db_session.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
    )
    assert left == 0


def test_hard_delete_rejects_admin_and_root(client, admin_user, normal_admin):
    root = _root_headers(client, admin_user)
    admins = client.get("/api/admin/users", headers=root, params={"role": "admin"}).json()
    root_row = next(u for u in admins if u["email"] == "root")
    ops_row = next(u for u in admins if u["email"] == "ops@lawbot.local")

    forbid_root = client.delete(f"/api/admin/users/{root_row['id']}", headers=root)
    assert forbid_root.status_code == 400
    assert "种子超级管理员" in forbid_root.json()["detail"] or "C 端用户" in forbid_root.json()["detail"]

    forbid_admin = client.delete(f"/api/admin/users/{ops_row['id']}", headers=root)
    assert forbid_admin.status_code == 400
    assert "只能硬删除 C 端用户" in forbid_admin.json()["detail"]


def test_hard_delete_requires_permission(client, admin_user, db_session):
    from lawbot.db.models import User
    from lawbot.domain.schemas import UserRole
    from lawbot.rbac.service import ensure_user_has_role
    from lawbot.security import hash_password

    root = _root_headers(client, admin_user)
    created = client.post(
        "/api/admin/users/clients",
        headers=root,
        json={"email": "keep_me@example.com", "password": "secret12"},
    )
    assert created.status_code == 201
    target_id = created.json()["id"]

    operator = User(
        email="operator@lawbot.local",
        password_hash=hash_password("OpsPass12"),
        display_name="Operator",
        role=UserRole.OPERATOR,
    )
    db_session.add(operator)
    db_session.flush()
    ensure_user_has_role(db_session, operator, UserRole.OPERATOR)
    db_session.commit()

    op_headers = _login(client, "operator@lawbot.local", "OpsPass12")
    denied = client.delete(f"/api/admin/users/{target_id}", headers=op_headers)
    assert denied.status_code == 403

    # disable still works for admins with user:disable
    ops = _login(client, "root", "Admin123!")
    still = client.patch(
        f"/api/admin/users/{target_id}",
        headers=ops,
        json={"disabled": True},
    )
    assert still.status_code == 200
    assert still.json()["disabled"] is True
