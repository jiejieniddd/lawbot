from __future__ import annotations

from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    """Shared Redis connection pool (singleton client)."""
    settings = get_settings()
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )


def redis_ping() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
