from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lawbot.db.models import Permission, Role, RolePermission
from lawbot.rbac.permissions import PERMISSION_DEFS, ROLE_DEFS, ROLE_PERMISSION_CODES
from lawbot.rbac.service import ensure_user_has_role, get_role_by_code


def seed_rbac_catalog(db: Session, *, commit: bool = False) -> None:
    """Idempotent seed of permissions, roles, and role_permissions."""
    perm_by_code: dict[str, Permission] = {
        p.code: p for p in db.scalars(select(Permission)).all()
    }
    for defn in PERMISSION_DEFS:
        row = perm_by_code.get(defn["code"])
        if row is None:
            row = Permission(
                code=defn["code"],
                name=defn["name"],
                module=defn["module"],
                description=defn["description"],
            )
            db.add(row)
            perm_by_code[defn["code"]] = row
        else:
            row.name = defn["name"]
            row.module = defn["module"]
            row.description = defn["description"]
    db.flush()

    role_by_code: dict[str, Role] = {r.code: r for r in db.scalars(select(Role)).all()}
    for defn in ROLE_DEFS:
        row = role_by_code.get(defn["code"])
        if row is None:
            row = Role(
                code=defn["code"],
                name=defn["name"],
                description=defn["description"],
                is_system=defn["is_system"],
                enabled=True,
            )
            db.add(row)
            role_by_code[defn["code"]] = row
        else:
            row.name = defn["name"]
            row.description = defn["description"]
            row.is_system = defn["is_system"]
    db.flush()

    for role_code, codes in ROLE_PERMISSION_CODES.items():
        role = role_by_code[role_code]
        existing = {
            rp.permission_id
            for rp in db.scalars(
                select(RolePermission).where(RolePermission.role_id == role.id)
            ).all()
        }
        # Only add missing defaults; never strip customizations made via Admin UI
        for code in codes:
            pid = perm_by_code[code].id
            if pid not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=pid))
    db.flush()
    if commit:
        db.commit()


def assign_primary_role_by_user_role_column(db: Session, user) -> None:
    code = str(user.role or "user")
    if get_role_by_code(db, code) is None:
        code = "user"
    ensure_user_has_role(db, user, code)
