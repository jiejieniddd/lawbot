"""LangGraph checkpointer factory aligned with DATABASE_URL.

Thread contract (same conversation continuity):
- ``thread_id = str(conversation_id)`` (UUID string, << 255 chars).
- Reuse the same conversation_id for multi-turn follow-ups within one chat.
- 「新咨询」creates a new conversation → new thread; short-term slots do not leak.
- Production should use postgresql:// so PostgresSaver survives API restarts.
  Falling back to MemorySaver loses slots on process restart (logged as error).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any
from urllib.parse import urlparse

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, Any] = {}
# url/key → backend label for logging / delete_thread
_backend_by_key: dict[str, str] = {}


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


def _cache_put(key: str, saver: Any, backend: str) -> Any:
    _cache[key] = saver
    _backend_by_key[key] = backend
    logger.info("checkpointer ready backend=%s key=%s", backend, key[:48])
    return saver


def get_checkpointer(database_url: str | None = None, *, force_memory: bool = False) -> Any:
    """Return a process-cached checkpointer.

    - force_memory / empty URL → MemorySaver
    - postgresql → PostgresSaver (langgraph-checkpoint-postgres)
    - sqlite → SqliteSaver (langgraph-checkpoint-sqlite)

    thread_id must be ``str(conversation_id)`` when invoking the graph.
    """
    if force_memory or not (database_url or "").strip():
        key = "memory"
        with _lock:
            if key not in _cache:
                if not force_memory:
                    logger.error(
                        "checkpointer backend=memory production_risk=true "
                        "(empty DATABASE_URL); same conversation slots are lost on API restart"
                    )
                return _cache_put(key, MemorySaver(), "memory")
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
                logger.exception(
                    "Postgres checkpointer unavailable; falling back to MemorySaver "
                    "production_risk=true — same conversation slots lost on API restart"
                )
                return _cache_put(key, MemorySaver(), "memory")
            try:
                conninfo = _normalize_postgres_conninfo(url)
                pool = ConnectionPool(conninfo=conninfo, kwargs={"autocommit": True}, open=True)
                saver = PostgresSaver(pool)
                saver.setup()
                return _cache_put(key, saver, "postgres")
            except Exception:
                logger.exception(
                    "Postgres checkpointer setup failed; falling back to MemorySaver "
                    "production_risk=true — same conversation slots lost on API restart"
                )
                return _cache_put(key, MemorySaver(), "memory")

        if url.startswith("sqlite"):
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = _sqlite_path(url)
            if path == ":memory:":
                logger.error(
                    "checkpointer backend=memory production_risk=true "
                    "(sqlite :memory:); slots lost on API restart"
                )
                return _cache_put(key, MemorySaver(), "memory")
            conn = sqlite3.connect(path, check_same_thread=False)
            saver = SqliteSaver(conn)
            saver.setup()
            return _cache_put(key, saver, "sqlite")

        logger.error(
            "Unknown DATABASE_URL scheme for checkpointer; using MemorySaver "
            "production_risk=true — same conversation slots lost on API restart"
        )
        return _cache_put(key, MemorySaver(), "memory")


def delete_thread_checkpoints(database_url: str | None, thread_id: str) -> bool:
    """Best-effort clear of one conversation thread from the checkpointer.

    Returns True if a delete was attempted successfully.
    Used when the user deletes a conversation (新咨询 does not need this —
    it simply uses a new conversation_id / thread_id).
    """
    tid = str(thread_id or "").strip()
    if not tid:
        return False
    try:
        saver = get_checkpointer(database_url)
        if hasattr(saver, "delete_thread"):
            saver.delete_thread(tid)
            logger.info("checkpointer delete_thread ok thread_id=%s", tid)
            return True
        logger.warning(
            "checkpointer has no delete_thread; skipped cleanup thread_id=%s backend=%s",
            tid,
            _backend_by_key.get((database_url or "").strip() or "memory", "?"),
        )
        return False
    except Exception:
        logger.exception("checkpointer delete_thread failed thread_id=%s", tid)
        return False


def clear_checkpointer_cache() -> None:
    with _lock:
        _cache.clear()
        _backend_by_key.clear()
