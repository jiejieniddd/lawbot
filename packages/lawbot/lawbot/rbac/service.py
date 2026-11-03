from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from lawbot.db.models import Permission, Role, RolePermission, User, UserRoleAssignment
from lawbot.domain.schemas import UserRole, is_super_admin_role


def get_role_by_code(db: Session, code: str) -> Role | None:
    return db.scalar(select(Role).where(Role.code == code))


def list_user_roles(db: Session, user: User) -> list[Role]:
    rows = db.scalars(
        select(Role)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .where(UserRoleAssignment.user_id == user.id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
    ).all()
    return list(rows)


def list_permission_codes(db: Session, user: User) -> set[str]:
    if is_super_admin_role(user.role):
        rows = db.scalars(select(Permission.code)).all()
        return set(rows)

    codes = db.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
        .where(
            UserRoleAssignment.user_id == user.id,
            Role.enabled.is_(True),
        )
    ).all()
    return set(codes)


def user_has_permission(db: Session, user: User, code: str) -> bool:
    if is_super_admin_role(user.role):
        return True
    return code in list_permission_codes(db, user)


def user_is_staff(user: User) -> bool:
    """Staff can enter admin shell: any non-end-user primary role."""
    return str(user.role) != UserRole.USER


def set_user_role(db: Session, user: User, role: Role, *, commit: bool = False) -> User:
    db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id))
    db.add(UserRoleAssignment(user_id=user.id, role_id=role.id))
    user.role = role.code
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user


def ensure_user_has_role(db: Session, user: User, role_code: str) -> User:
    role = get_role_by_code(db, role_code)
    if role is None:
        raise ValueError(f"role not found: {role_code}")
    existing = db.scalar(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user.id,
            UserRoleAssignment.role_id == role.id,
        )
    )
    if existing is None or user.role != role.code:
        set_user_role(db, user, role, commit=False)
    return user
