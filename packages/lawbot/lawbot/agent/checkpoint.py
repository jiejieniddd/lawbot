"""LangGraph checkpointer factory aligned with DATABASE_URL."""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any
from urllib.parse import urlparse, urlunparse

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _normalize_postgres_conninfo(database_url: str) -> str:
    """SQLAlchemy postgresql+psycopg://… → postgresql://… for psycopg."""
    url = database_url.strip()
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgres+psycopg://"):
        return "postgresql://" + url[len("postgres+psycopg://") :]
    return url


def _sqlite_path(database_url: str) -> str:
    raw = database_url.strip()
    if raw in {"sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:
        return ":memory:"
    if ":///" in raw:
        return raw.split(":///", 1)[1]
    parsed = urlparse(raw)
    return parsed.path.lstrip("/") or ":memory:"


def get_checkpointer(database_url: str | None = None, *, force_memory: bool = False) -> Any:
    """Return a process-cached checkpointer.

    - force_memory / empty URL → MemorySaver
    - postgresql → PostgresSaver (langgraph-checkpoint-postgres)
    - sqlite → SqliteSaver (langgraph-checkpoint-sqlite)
    """
    if force_memory or not (database_url or "").strip():
        key = "memory"
        with _lock:
            if key not in _cache:
                _cache[key] = MemorySaver()
            return _cache[key]

    url = database_url.strip()
    key = url
    with _lock:
        if key in _cache:
            return _cache[key]

        if url.startswith("postgres"):
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                from psycopg_pool import ConnectionPool
            except Exception:
                logger.exception("Postgres checkpointer unavailable; falling back to MemorySaver")
                saver: Any = MemorySaver()
                _cache[key] = saver
                return saver
            conninfo = _normalize_postgres_conninfo(url)
            pool = ConnectionPool(conninfo=conninfo, kwargs={"autocommit": True}, open=True)
            saver = PostgresSaver(pool)
            saver.setup()
            _cache[key] = saver
            return saver

        if url.startswith("sqlite"):
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = _sqlite_path(url)
            # Dedicated file so :memory: shared cache works across connections if needed
            if path == ":memory:":
                saver = MemorySaver()
            else:
                conn = sqlite3.connect(path, check_same_thread=False)
                saver = SqliteSaver(conn)
                saver.setup()
            _cache[key] = saver
            return saver

        logger.warning("Unknown DATABASE_URL scheme for checkpointer; using MemorySaver")
        saver = MemorySaver()
        _cache[key] = saver
        return saver


def clear_checkpointer_cache() -> None:
    with _lock:
        _cache.clear()
