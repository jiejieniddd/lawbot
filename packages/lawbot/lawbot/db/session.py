from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@lru_cache
def get_engine(database_url: str) -> Engine:
    connect_args: dict = {}
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # Keep a single shared in-memory DB across connections
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
            kwargs["pool_pre_ping"] = False
    return create_engine(database_url, connect_args=connect_args, **kwargs)


@lru_cache
def get_sessionmaker(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, autocommit=False)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return get_sessionmaker(database_url)


def session_scope(database_url: str) -> Generator[Session, None, None]:
    factory = get_sessionmaker(database_url)
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
