from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_admin, require_super_admin
from lawbot.db.models import User
from lawbot.domain.schemas import (
    AdminCreate,
    ClientCreate,
    UserOut,
    UserPatch,
    UserRole,
    is_staff_role,
    is_super_admin_role,
)
from lawbot.security import hash_password

router = APIRouter(prefix="/users", tags=["admin-users"])


def _normalize_account(value: str) -> str:
    return value.lower().strip()


def _is_protected_super(user: User, settings: Settings) -> bool:
    seed = settings.seed_admin_email.lower().strip()
    return is_super_admin_role(user.role) or user.email == seed


@router.get("", response_model=list[UserOut])
def list_users(
    role: UserRole = Query(..., description="Filter by role: user or admin (admin includes super_admin)"),
    q: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    if role == UserRole.USER:
        stmt = select(User).where(User.role == UserRole.USER)
    elif role == UserRole.ADMIN:
        stmt = select(User).where(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]))
    elif role == UserRole.SUPER_ADMIN:
        stmt = select(User).where(User.role == UserRole.SUPER_ADMIN)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role filter")

    stmt = stmt.order_by(User.created_at.desc())
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(term), User.display_name.ilike(term)))
    return list(db.scalars(stmt).all())


@router.post("/admins", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_admin(
    body: AdminCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_super_admin),
) -> User:
    email = _normalize_account(body.email)
    seed = settings.seed_admin_email.lower().strip()
    if email == seed or email == "root":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能创建超级管理员账号")
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已存在")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=UserRole.ADMIN,
        disabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/clients", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    email = _normalize_account(body.email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已存在")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or email.split("@")[0],
        role=UserRole.USER,
        disabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: UUID,
    body: UserPatch,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current: User = Depends(require_admin),
) -> User:
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
                    User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
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
    return user
