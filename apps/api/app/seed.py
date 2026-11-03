from __future__ import annotations

from sqlalchemy import select, update

from app.config import get_settings
from lawbot.db.models import User
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import UserRole
from lawbot.rbac.seed import seed_rbac_catalog
from lawbot.rbac.service import ensure_user_has_role
from lawbot.security import hash_password


def seed_admin() -> None:
    settings = get_settings()
    factory = get_sessionmaker(settings.database_url)
    db = factory()
    email = settings.seed_admin_email.lower().strip()
    try:
        seed_rbac_catalog(db, commit=False)

        # Ensure uniqueness: demote any other super_admin accounts
        db.execute(
            update(User)
            .where(User.role == UserRole.SUPER_ADMIN, User.email != email)
            .values(role=UserRole.ADMIN)
        )
        demoted = db.scalars(
            select(User).where(User.role == UserRole.ADMIN, User.email != email)
        ).all()
        for u in demoted:
            if u.email != email:
                ensure_user_has_role(db, u, UserRole.ADMIN)

        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            existing.role = UserRole.SUPER_ADMIN
            existing.disabled = False
            existing.password_hash = hash_password(settings.seed_admin_password)
            if not existing.display_name or existing.display_name == "Admin":
                existing.display_name = "超级管理员"
            ensure_user_has_role(db, existing, UserRole.SUPER_ADMIN)
            print(f"Updated super admin: {existing.email}")
        else:
            admin = User(
                email=email,
                password_hash=hash_password(settings.seed_admin_password),
                display_name="超级管理员",
                role=UserRole.SUPER_ADMIN,
                disabled=False,
            )
            db.add(admin)
            db.flush()
            ensure_user_has_role(db, admin, UserRole.SUPER_ADMIN)
            print(f"Created super admin: {admin.email}")
        db.commit()
    finally:
        db.close()


def main() -> None:
    seed_admin()


if __name__ == "__main__":
    main()
