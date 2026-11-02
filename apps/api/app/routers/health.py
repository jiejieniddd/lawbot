from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.redis_client import redis_ping

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    redis_ok = redis_ping()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "postgres": db_ok, "redis": redis_ok}
