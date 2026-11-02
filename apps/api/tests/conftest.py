from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Force SQLite before importing app modules that cache settings/engine
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["SEED_ADMIN_EMAIL"] = "root"
os.environ["SEED_ADMIN_PASSWORD"] = "Admin123!"
os.environ["RETRIEVER_MODE"] = "fake"
os.environ["EMBEDDING_MODE"] = "fake"
os.environ["IMPORT_MAX_ROWS"] = "500"

from app.config import get_settings
from lawbot.db.models import Base, User
from lawbot.db.session import get_engine, get_sessionmaker
from lawbot.domain.schemas import UserRole
from lawbot.security import hash_password

get_settings.cache_clear()
get_engine.cache_clear()
get_sessionmaker.cache_clear()


@pytest.fixture()
def db_engine():
    settings = get_settings()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    engine = get_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture()
def db_session(db_engine) -> Session:
    factory = get_sessionmaker(get_settings().database_url)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine):
    from app.main import app
    from app.redis_client import get_redis

    get_redis.cache_clear()

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_user(db_session: Session) -> User:
    """Unique super admin (root)."""
    user = User(
        email="root",
        password_hash=hash_password("Admin123!"),
        display_name="超级管理员",
        role=UserRole.SUPER_ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def normal_admin(db_session: Session, admin_user: User) -> User:
    user = User(
        email="ops@lawbot.local",
        password_hash=hash_password("OpsPass12"),
        display_name="Ops",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
