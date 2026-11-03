"""RBAC roles, permissions, and user_roles

Revision ID: 006_rbac
Revises: 005_user_avatar
Create Date: 2026-11-03

"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from lawbot.rbac.permissions import PERMISSION_DEFS, ROLE_DEFS, ROLE_PERMISSION_CODES

revision: str = "006_rbac"
down_revision: Union[str, None] = "005_user_avatar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "permissions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"])
    op.create_index("ix_permissions_module", "permissions", ["module"])

    op.create_table(
        "roles",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_roles_code", "roles", ["code"])

    op.create_table(
        "role_permissions",
        sa.Column("role_id", uuid_type, nullable=False),
        sa.Column("permission_id", uuid_type, nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("role_id", uuid_type, nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    conn = op.get_bind()
    perm_ids: dict[str, uuid.UUID] = {}
    for p in PERMISSION_DEFS:
        pid = _uuid()
        perm_ids[p["code"]] = pid
        conn.execute(
            sa.text(
                "INSERT INTO permissions (id, code, name, module, description) "
                "VALUES (:id, :code, :name, :module, :description)"
            ),
            {
                "id": pid,
                "code": p["code"],
                "name": p["name"],
                "module": p["module"],
                "description": p["description"],
            },
        )

    role_ids: dict[str, uuid.UUID] = {}
    for r in ROLE_DEFS:
        rid = _uuid()
        role_ids[r["code"]] = rid
        conn.execute(
            sa.text(
                "INSERT INTO roles (id, code, name, description, is_system, enabled) "
                "VALUES (:id, :code, :name, :description, :is_system, true)"
            ),
            {
                "id": rid,
                "code": r["code"],
                "name": r["name"],
                "description": r["description"],
                "is_system": r["is_system"],
            },
        )

    for role_code, codes in ROLE_PERMISSION_CODES.items():
        rid = role_ids[role_code]
        for code in codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "VALUES (:role_id, :permission_id)"
                ),
                {"role_id": rid, "permission_id": perm_ids[code]},
            )

    # Backfill user_roles from users.role
    users = conn.execute(sa.text("SELECT id, role, lower(email) AS email FROM users")).mappings().all()
    for u in users:
        code = u["role"] or "user"
        if u["email"] == "root" or code == "super_admin":
            code = "super_admin"
        elif code not in role_ids:
            code = "user"
        conn.execute(
            sa.text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
            {"user_id": u["id"], "role_id": role_ids[code]},
        )
        if u["role"] != code:
            conn.execute(
                sa.text("UPDATE users SET role = :role WHERE id = :id"),
                {"role": code, "id": u["id"]},
            )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_permissions_module", table_name="permissions")
    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")
