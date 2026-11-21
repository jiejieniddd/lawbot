"""Cross-conversation user memory (not a second law RAG).

Namespace: (\"memories\", \"{user_id}\").
Values: typed JSON {text, type, updated_at} where type is preference|case_fact|entity.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MemoryNamespace = tuple[str, str]


def memories_namespace(user_id: str) -> MemoryNamespace:
    return ("memories", str(user_id))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _overlap_score(query: str, text: str) -> float:
    q = (query or "").strip()
    t = (text or "").strip()
    if not q or not t:
        return 0.0
    if q in t or t in q:
        return 10.0 + min(len(t), 40) / 40.0
    # Character overlap for CN; token-ish for ASCII.
    q_chars = set(q)
    hit = sum(1 for ch in t if ch in q_chars)
    return float(hit) / max(len(q_chars), 1)


class MemoryStore(Protocol):
    def put(self, namespace: MemoryNamespace, key: str, value: dict[str, Any]) -> None: ...

    def search(
        self,
        namespace: MemoryNamespace,
        *,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...


class InMemoryMemoryStore:
    """Process-local store for tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[tuple[str, str, str], dict[str, Any]] = {}

    def put(self, namespace: MemoryNamespace, key: str, value: dict[str, Any]) -> None:
        ns0, ns1 = namespace
        body = dict(value or {})
        body.setdefault("updated_at", _utcnow())
        with self._lock:
            self._data[(ns0, ns1, key)] = body

    def search(
        self,
        namespace: MemoryNamespace,
        *,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        ns0, ns1 = namespace
        scored: list[tuple[float, dict[str, Any]]] = []
        with self._lock:
            for (a, b, _key), val in self._data.items():
                if a != ns0 or b != ns1:
                    continue
                text = str(val.get("text") or "")
                score = _overlap_score(query, text)
                if score <= 0 and not query.strip():
                    score = 0.1
                if score > 0:
                    item = dict(val)
                    item["score"] = score
                    scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [v for _s, v in scored[: max(1, limit)]]


class SqlAlchemyMemoryStore:
    """Postgres/SQLite-backed long memories via SQLAlchemy Session factory."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def put(self, namespace: MemoryNamespace, key: str, value: dict[str, Any]) -> None:
        from lawbot.db.models import UserLongMemory

        ns0, ns1 = namespace
        if ns0 != "memories":
            return
        try:
            user_uuid = uuid.UUID(str(ns1))
        except ValueError:
            logger.warning("memory put skipped invalid user_id=%s", ns1)
            return
        body = dict(value or {})
        text = str(body.get("text") or "").strip()
        if not text:
            return
        mem_type = str(body.get("type") or "case_fact").strip() or "case_fact"
        session = self._session_factory()
        try:
            row = (
                session.query(UserLongMemory)
                .filter_by(user_id=user_uuid, mem_key=key)
                .one_or_none()
            )
            if row is None:
                row = UserLongMemory(
                    user_id=user_uuid,
                    mem_key=key,
                    text=text[:1000],
                    mem_type=mem_type[:32],
                )
                session.add(row)
            else:
                row.text = text[:1000]
                row.mem_type = mem_type[:32]
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("SqlAlchemyMemoryStore.put failed")
        finally:
            session.close()

    def search(
        self,
        namespace: MemoryNamespace,
        *,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        from lawbot.db.models import UserLongMemory

        ns0, ns1 = namespace
        if ns0 != "memories":
            return []
        try:
            user_uuid = uuid.UUID(str(ns1))
        except ValueError:
            return []
        session = self._session_factory()
        try:
            rows = (
                session.query(UserLongMemory)
                .filter_by(user_id=user_uuid)
                .order_by(UserLongMemory.updated_at.desc())
                .limit(50)
                .all()
            )
            scored: list[tuple[float, dict[str, Any]]] = []
            for row in rows:
                text = row.text or ""
                score = _overlap_score(query, text)
                if score <= 0 and not (query or "").strip():
                    score = 0.1
                if score <= 0:
                    continue
                scored.append(
                    (
                        score,
                        {
                            "text": text,
                            "type": row.mem_type,
                            "updated_at": row.updated_at.isoformat()
                            if row.updated_at
                            else _utcnow(),
                            "score": score,
                            "key": row.mem_key,
                        },
                    )
                )
            scored.sort(key=lambda x: x[0], reverse=True)
            return [v for _s, v in scored[: max(1, limit)]]
        except Exception:
            logger.exception("SqlAlchemyMemoryStore.search failed")
            return []
        finally:
            session.close()


_store_lock = threading.Lock()
_store_cache: dict[str, MemoryStore] = {}


def get_memory_store(database_url: str | None = None) -> MemoryStore:
    """Process-cached store; InMemory when URL empty or init fails (tests/degrade)."""
    key = (database_url or "").strip() or "memory"
    with _store_lock:
        if key in _store_cache:
            return _store_cache[key]
        if key == "memory":
            store: MemoryStore = InMemoryMemoryStore()
            _store_cache[key] = store
            return store
        try:
            from lawbot.db.session import get_sessionmaker

            store = SqlAlchemyMemoryStore(get_sessionmaker(key))
            _store_cache[key] = store
            return store
        except Exception:
            logger.exception("SqlAlchemy memory store init failed; using InMemory")
            store = InMemoryMemoryStore()
            _store_cache[key] = store
            return store


def put_preference_memories(
    store: MemoryStore,
    *,
    user_id: str,
    province: str | None = None,
    case_domain: str | None = None,
) -> None:
    """Sync durable prefs into Store (safe, no dispute narrative)."""
    ns = memories_namespace(user_id)
    try:
        if province:
            store.put(
                ns,
                "pref:province",
                {"text": f"用户地区偏好：{province}", "type": "preference", "updated_at": _utcnow()},
            )
        if case_domain and case_domain != "general":
            store.put(
                ns,
                "pref:case_domain",
                {
                    "text": f"用户近期常见案由：{case_domain}",
                    "type": "preference",
                    "updated_at": _utcnow(),
                },
            )
    except Exception:
        logger.exception("put_preference_memories failed user_id=%s", user_id)


def search_user_memories(
    store: MemoryStore | None,
    *,
    user_id: str,
    query: str,
    limit: int = 4,
) -> list[dict[str, Any]]:
    if store is None or not user_id:
        return []
    try:
        return store.search(memories_namespace(user_id), query=query, limit=limit)
    except Exception:
        logger.exception("search_user_memories failed")
        return []
