from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_permission
from app.services.rbac_out import user_to_out
from lawbot.accounts import normalize_account as _normalize_account
from lawbot.db.models import Role, User
from lawbot.domain.schemas import (
    AdminCreate,
    ClientCreate,
    UserOut,
    UserPatch,
    UserRole,
    UserRoleAssign,
    is_staff_role,
    is_super_admin_role,
)
from lawbot.rbac.service import get_role_by_code, set_user_role
from lawbot.security import hash_password

router = APIRouter(prefix="/users", tags=["admin-users"])


def _is_protected_super(user: User, settings: Settings) -> bool:
    seed = settings.seed_admin_email.lower().strip()
    return is_super_admin_role(user.role) or user.email == seed


@router.get("", response_model=list[UserOut])
def list_users(
    role: UserRole = Query(..., description="Filter by role: user or admin (admin includes staff)"),
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user:list")),
) -> list[UserOut]:
    if role == UserRole.USER:
        stmt = select(User).where(User.role == UserRole.USER)
    elif role == UserRole.ADMIN:
        stmt = select(User).where(
            User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATOR])
        )
    elif role == UserRole.SUPER_ADMIN:
        stmt = select(User).where(User.role == UserRole.SUPER_ADMIN)
    elif role == UserRole.OPERATOR:
        stmt = select(User).where(User.role == UserRole.OPERATOR)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role filter")

    stmt = stmt.order_by(User.created_at.desc())
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(term), User.display_name.ilike(term)))
    users = list(db.scalars(stmt).all())
    return [user_to_out(db, u, with_permissions=False) for u in users]


@router.post("/admins", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_admin(
    body: AdminCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission("admin:manage")),
) -> UserOut:
    email = _normalize_account(body.email)
    seed = settings.seed_admin_email.lower().strip()
    if email == seed or email == "root":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能创建超级管理员账号")
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已存在")

    if body.role_id is not None:
        role = db.get(Role, body.role_id)
        if role is None or role.code in (UserRole.USER, UserRole.SUPER_ADMIN) or not role.enabled:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的管理员角色")
    else:
        role = get_role_by_code(db, UserRole.ADMIN)
        if role is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="角色未初始化")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=role.code,
        disabled=False,
    )
    db.add(user)
    db.flush()
    set_user_role(db, user, role)
    db.commit()
    db.refresh(user)
    return user_to_out(db, user, with_permissions=False)


@router.post("/clients", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("user:create")),
) -> UserOut:
    email = _normalize_account(body.email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已存在")

    if body.role_id is not None:
        role = db.get(Role, body.role_id)
        if role is None or role.code != UserRole.USER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="C 端用户只能分配普通用户角色")
    else:
        role = get_role_by_code(db, UserRole.USER)
        if role is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="角色未初始化")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or email,
        role=role.code,
        disabled=False,
    )
    db.add(user)
    db.flush()
    set_user_role(db, user, role)
    db.commit()
    db.refresh(user)
    return user_to_out(db, user, with_permissions=False)


@router.patch("/{user_id}/role", response_model=UserOut)
def assign_user_role(
    user_id: UUID,
    body: UserRoleAssign,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current: User = Depends(require_permission("admin:manage")),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role = db.get(Role, body.role_id)
    if role is None or not role.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不存在或已禁用")

    if _is_protected_super(user, settings) and role.code != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除超级管理员角色")
    if user.id == current.id and is_super_admin_role(current.role) and role.code != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除自己的超级管理员角色")
    if role.code == UserRole.SUPER_ADMIN and not is_super_admin_role(current.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权分配超级管理员")

    # Managing end-user role assignment still allowed via admin:manage for staff targets;
    # clients should stay on user role unless elevating carefully.
    if user.role == UserRole.USER and role.code != UserRole.USER:
        if not is_super_admin_role(current.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权提升 C 端用户为管理员")

    set_user_role(db, user, role)
    db.commit()
    db.refresh(user)
    return user_to_out(db, user, with_permissions=False)


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: UUID,
    body: UserPatch,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current: User = Depends(require_permission("user:disable")),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if _is_protected_super(user, settings):
        if body.disabled is True:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能禁用超级管理员",
            )
        if body.display_name is not None and body.display_name != user.display_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能修改超级管理员",
            )

    if not is_super_admin_role(current.role) and is_staff_role(user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="普通管理员只能管理 C 端用户",
        )

    if body.disabled is True:
        if user.id == current.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能禁用当前登录管理员",
            )
        if is_staff_role(user.role) and not user.disabled:
            other_enabled = db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATOR]),
                    User.disabled.is_(False),
                    User.id != user.id,
                )
            )
            if not other_enabled:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="至少保留一名可登录后台的管理员",
                )

    if body.disabled is not None:
        user.disabled = body.disabled
    if body.display_name is not None:
        user.display_name = body.display_name
    db.commit()
    db.refresh(user)
    return user_to_out(db, user, with_permissions=False)
