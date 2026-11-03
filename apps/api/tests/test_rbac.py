from __future__ import annotations

from sqlalchemy.orm import Session

from lawbot.domain.schemas import UserRole
from lawbot.rbac.service import get_role_by_code


def _login(client, email: str, password: str) -> dict:
    resp = client.post("/api/admin/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_super_admin_me_has_permissions(client, admin_user, db_session: Session):
    headers = _login(client, "root", "Admin123!")
    me = client.get("/api/admin/auth/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "super_admin"
    assert "role:manage" in body["permissions"]
    assert "knowledge:import" in body["permissions"]
    assert any(r["code"] == "super_admin" for r in body["roles"])


def test_roles_crud_and_permission_gate(client, admin_user, normal_admin, db_session: Session):
    root = _login(client, "root", "Admin123!")
    ops = _login(client, "ops@lawbot.local", "OpsPass12")

    denied = client.get("/api/admin/roles", headers=ops)
    assert denied.status_code == 403

    roles = client.get("/api/admin/roles", headers=root)
    assert roles.status_code == 200
    assert any(r["code"] == "admin" for r in roles.json())

    created = client.post(
        "/api/admin/roles",
        headers=root,
        json={"code": "content_ops", "name": "内容运营", "description": "custom", "enabled": True},
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    put = client.put(
        f"/api/admin/roles/{role_id}/permissions",
        headers=root,
        json={"permission_codes": ["stats:read", "knowledge:read"]},
    )
    assert put.status_code == 200
    assert set(put.json()["permission_codes"]) == {"stats:read", "knowledge:read"}


def test_strip_import_permission_blocks_job_create(
    client, admin_user, normal_admin, db_session: Session
):
    root = _login(client, "root", "Admin123!")
    admin_role = get_role_by_code(db_session, UserRole.ADMIN)
    assert admin_role is not None

    # Remove knowledge:import from admin role
    perms = client.get("/api/admin/roles", headers=root).json()
    admin_row = next(r for r in perms if r["code"] == "admin")
    codes = [c for c in admin_row["permission_codes"] if c != "knowledge:import"]
    upd = client.put(
        f"/api/admin/roles/{admin_row['id']}/permissions",
        headers=root,
        json={"permission_codes": codes},
    )
    assert upd.status_code == 200
    assert "knowledge:import" not in upd.json()["permission_codes"]

    ops = _login(client, "ops@lawbot.local", "OpsPass12")
    me = client.get("/api/admin/auth/me", headers=ops)
    assert me.status_code == 200
    assert "knowledge:import" not in me.json()["permissions"]

    denied = client.post("/api/admin/knowledge-import-jobs", headers=ops, json={})
    assert denied.status_code == 403

    # Still can list jobs with knowledge:read
    listed = client.get("/api/admin/knowledge-import-jobs", headers=ops)
    assert listed.status_code == 200


def test_assign_role_changes_permissions(client, admin_user, db_session: Session):
    root = _login(client, "root", "Admin123!")
    # create operator user via admin create + assign
    created = client.post(
        "/api/admin/users/admins",
        headers=root,
        json={"email": "op_user", "password": "OpsPass12", "display_name": "Op"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    roles = client.get("/api/admin/role-options", headers=root).json()
    operator = next(r for r in roles if r["code"] == "operator")
    assigned = client.patch(
        f"/api/admin/users/{user_id}/role",
        headers=root,
        json={"role_id": operator["id"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["role"] == "operator"

    op_headers = _login(client, "op_user", "OpsPass12")
    me = client.get("/api/admin/auth/me", headers=op_headers).json()
    assert set(me["permissions"]) == {"stats:read", "audit:read", "knowledge:read"}

    deny_providers = client.get("/api/admin/llm-providers", headers=op_headers)
    assert deny_providers.status_code == 403


def test_cannot_strip_own_super_admin(client, admin_user, db_session: Session):
    root = _login(client, "root", "Admin123!")
    me = client.get("/api/admin/auth/me", headers=root).json()
    roles = client.get("/api/admin/role-options", headers=root).json()
    admin_role = next(r for r in roles if r["code"] == "admin")
    resp = client.patch(
        f"/api/admin/users/{me['id']}/role",
        headers=root,
        json={"role_id": admin_role["id"]},
    )
    assert resp.status_code == 400
    assert "超级管理员" in resp.json()["detail"]


def test_end_user_admin_api_still_403(client, admin_user, db_session: Session):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "cuser99", "password": "secret12"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/auth/me", headers=headers).status_code == 403
    assert client.get("/api/admin/roles", headers=headers).status_code == 403
