from __future__ import annotations

from lawbot.db.models import User
from lawbot.domain.schemas import RoleBrief, UserOut
from lawbot.rbac.service import list_permission_codes, list_user_roles
from sqlalchemy.orm import Session


def to_user_out(db: Session, user: User, *, with_permissions: bool = False) -> UserOut:
    roles = list_user_roles(db, user)
    perms: list[str] = []
    if with_permissions:
        perms = sorted(list_permission_codes(db, user))
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        disabled=user.disabled,
        created_at=user.created_at,
        avatar_url=user.avatar_url,
        roles=[RoleBrief(id=r.id, code=r.code, name=r.name) for r in roles],
        permissions=perms,
    )
