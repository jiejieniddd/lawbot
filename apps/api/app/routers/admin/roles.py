from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import get_db, require_permission
from lawbot.db.models import Permission, Role, RolePermission, User
from lawbot.domain.schemas import (
    PermissionOut,
    RoleBrief,
    RoleCreate,
    RoleOut,
    RolePatch,
    RolePermissionsUpdate,
)
from lawbot.rbac.service import get_role_by_code

router = APIRouter(tags=["admin-roles"])


def _role_out(role: Role) -> RoleOut:
    codes = sorted(
        rp.permission.code
        for rp in role.role_permissions
        if rp.permission is not None
    )
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        enabled=role.enabled,
        permission_codes=codes,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _load_role(db: Session, role_id: UUID) -> Role:
    role = db.scalar(
        select(Role)
        .where(Role.id == role_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
    )
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


@router.get("/permissions", response_model=dict[str, list[PermissionOut]])
def list_permissions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> dict[str, list[PermissionOut]]:
    rows = list(db.scalars(select(Permission).order_by(Permission.module, Permission.code)).all())
    grouped: dict[str, list[PermissionOut]] = {}
    for p in rows:
        grouped.setdefault(p.module, []).append(PermissionOut.model_validate(p))
    return grouped


@router.get("/role-options", response_model=list[RoleBrief])
def list_role_options(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("admin:manage")),
) -> list[RoleBrief]:
    """Lightweight role list for user assignment dropdowns."""
    _ = user
    roles = db.scalars(select(Role).where(Role.enabled.is_(True)).order_by(Role.code)).all()
    return [RoleBrief(id=r.id, code=r.code, name=r.name) for r in roles]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("role:manage")),
) -> list[RoleOut]:
    _ = user
    roles = db.scalars(
        select(Role)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        .order_by(Role.code)
    ).all()
    return [_role_out(r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> RoleOut:
    if get_role_by_code(db, body.code) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色编码已存在")
    role = Role(
        code=body.code,
        name=body.name,
        description=body.description,
        is_system=False,
        enabled=body.enabled,
    )
    db.add(role)
    db.commit()
    return _role_out(_load_role(db, role.id))


@router.get("/roles/{role_id}", response_model=RoleOut)
def get_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> RoleOut:
    return _role_out(_load_role(db, role_id))


@router.patch("/roles/{role_id}", response_model=RoleOut)
def patch_role(
    role_id: UUID,
    body: RolePatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> RoleOut:
    role = _load_role(db, role_id)
    if role.code == "super_admin" and body.enabled is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用超级管理员角色")
    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.enabled is not None:
        role.enabled = body.enabled
    db.commit()
    return _role_out(_load_role(db, role.id))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> None:
    role = _load_role(db, role_id)
    if role.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统角色不可删除")
    db.delete(role)
    db.commit()


@router.get("/roles/{role_id}/permissions", response_model=list[str])
def get_role_permissions(
    role_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> list[str]:
    return _role_out(_load_role(db, role_id)).permission_codes


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
def put_role_permissions(
    role_id: UUID,
    body: RolePermissionsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("role:manage")),
) -> RoleOut:
    role = _load_role(db, role_id)
    if role.code == "super_admin":
        # Keep super_admin as full set; ignore client attempt to strip
        perms = list(db.scalars(select(Permission)).all())
    else:
        wanted = set(body.permission_codes)
        perms = list(db.scalars(select(Permission).where(Permission.code.in_(wanted))).all())
        found = {p.code for p in perms}
        missing = wanted - found
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"未知权限: {', '.join(sorted(missing))}",
            )

    role.role_permissions.clear()
    db.flush()
    for p in perms:
        role.role_permissions.append(RolePermission(role_id=role.id, permission_id=p.id))
    db.commit()
    return _role_out(_load_role(db, role.id))
