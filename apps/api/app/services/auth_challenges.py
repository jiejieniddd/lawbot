from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.redis_client import get_redis
from lawbot.db.models import AuthChallenge

logger = logging.getLogger(__name__)

PURPOSE_RESET_PASSWORD = "reset_password"
PURPOSE_LOGIN_FAIL = "login_fail"

DEFAULT_MAX_ATTEMPTS = 5
LOGIN_FAIL_MAX_ATTEMPTS = 5
LOGIN_FAIL_LOCK_SECONDS = 15 * 60


def redis_key(purpose: str, subject: str) -> str:
    return f"lawbot:auth:challenge:{purpose}:{subject}"


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _ttl_seconds(expires_at: datetime) -> int:
    remaining = int((_aware(expires_at) - _now()).total_seconds())
    return max(1, remaining)


@dataclass
class ChallengeView:
    id: uuid.UUID
    purpose: str
    subject: str
    code_hash: str | None
    attempts: int
    max_attempts: int
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: AuthChallenge) -> ChallengeView:
        return cls(
            id=row.id,
            purpose=row.purpose,
            subject=row.subject,
            code_hash=row.code_hash,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            expires_at=_aware(row.expires_at),
            used_at=_aware(row.used_at) if row.used_at else None,
            created_at=_aware(row.created_at),
        )

    def is_expired(self) -> bool:
        return _aware(self.expires_at) <= _now()

    def is_usable(self) -> bool:
        return self.used_at is None and not self.is_expired()


def _serialize(view: ChallengeView) -> str:
    return json.dumps(
        {
            "id": str(view.id),
            "purpose": view.purpose,
            "subject": view.subject,
            "code_hash": view.code_hash,
            "attempts": view.attempts,
            "max_attempts": view.max_attempts,
            "expires_at": view.expires_at.isoformat(),
            "used_at": view.used_at.isoformat() if view.used_at else None,
            "created_at": view.created_at.isoformat(),
        },
        separators=(",", ":"),
    )


def _deserialize(raw: str) -> ChallengeView | None:
    try:
        data = json.loads(raw)
        used = data.get("used_at")
        return ChallengeView(
            id=uuid.UUID(data["id"]),
            purpose=str(data["purpose"]),
            subject=str(data["subject"]),
            code_hash=data.get("code_hash"),
            attempts=int(data.get("attempts") or 0),
            max_attempts=int(data.get("max_attempts") or DEFAULT_MAX_ATTEMPTS),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            used_at=datetime.fromisoformat(used) if used else None,
            created_at=datetime.fromisoformat(data["created_at"]),
        )
    except Exception:
        logger.exception("failed to deserialize auth challenge redis payload")
        return None


def _redis_set(view: ChallengeView) -> None:
    try:
        client = get_redis()
        client.set(redis_key(view.purpose, view.subject), _serialize(view), ex=_ttl_seconds(view.expires_at))
    except Exception:
        logger.exception(
            "redis set failed for auth challenge purpose=%s subject=%s",
            view.purpose,
            view.subject,
        )


def _redis_delete(purpose: str, subject: str) -> None:
    try:
        get_redis().delete(redis_key(purpose, subject))
    except Exception:
        logger.exception("redis delete failed for auth challenge purpose=%s subject=%s", purpose, subject)


def _redis_get(purpose: str, subject: str) -> ChallengeView | None:
    try:
        raw = get_redis().get(redis_key(purpose, subject))
    except Exception:
        logger.exception("redis get failed for auth challenge purpose=%s subject=%s", purpose, subject)
        return None
    if not raw:
        return None
    view = _deserialize(str(raw))
    if view is None or not view.is_usable():
        return None
    return view


def _invalidate_previous(db: Session, purpose: str, subject: str) -> None:
    now = _now()
    db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.purpose == purpose,
            AuthChallenge.subject == subject,
            AuthChallenge.used_at.is_(None),
        )
        .values(used_at=now)
    )


def create_challenge(
    db: Session,
    *,
    purpose: str,
    subject: str,
    code_hash: str | None,
    ttl_seconds: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    mark_used: bool = False,
    initial_attempts: int = 0,
) -> ChallengeView:
    """Postgres-first write; Redis best-effort. Commits the session."""
    _invalidate_previous(db, purpose, subject)
    now = _now()
    row = AuthChallenge(
        id=uuid.uuid4(),
        purpose=purpose,
        subject=subject,
        code_hash=code_hash,
        attempts=initial_attempts,
        max_attempts=max_attempts,
        expires_at=now + timedelta(seconds=max(1, ttl_seconds)),
        used_at=now if mark_used else None,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    view = ChallengeView.from_row(row)
    if mark_used:
        _redis_delete(purpose, subject)
    else:
        _redis_set(view)
    return view


def get_active_challenge(db: Session, purpose: str, subject: str) -> ChallengeView | None:
    cached = _redis_get(purpose, subject)
    if cached is not None:
        row = db.get(AuthChallenge, cached.id)
        if row is not None and row.used_at is None and _aware(row.expires_at) > _now():
            return ChallengeView.from_row(row)
        _redis_delete(purpose, subject)

    row = db.scalar(
        select(AuthChallenge)
        .where(
            AuthChallenge.purpose == purpose,
            AuthChallenge.subject == subject,
            AuthChallenge.used_at.is_(None),
            AuthChallenge.expires_at > _now(),
        )
        .order_by(AuthChallenge.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    view = ChallengeView.from_row(row)
    _redis_set(view)
    return view


def register_failed_attempt(db: Session, challenge: ChallengeView) -> ChallengeView:
    """Bump attempts. For reset codes, burn (used_at) at max; login_fail stays active as lock."""
    now = _now()
    new_attempts = challenge.attempts + 1
    values: dict = {"attempts": new_attempts}
    if challenge.purpose != PURPOSE_LOGIN_FAIL and new_attempts >= challenge.max_attempts:
        values["used_at"] = now
    if challenge.purpose == PURPOSE_LOGIN_FAIL and new_attempts >= challenge.max_attempts:
        # Refresh lock window from now
        values["expires_at"] = now + timedelta(seconds=LOGIN_FAIL_LOCK_SECONDS)
    db.execute(update(AuthChallenge).where(AuthChallenge.id == challenge.id).values(**values))
    db.commit()
    row = db.get(AuthChallenge, challenge.id)
    assert row is not None
    view = ChallengeView.from_row(row)
    if view.used_at is not None or not view.is_usable():
        _redis_delete(view.purpose, view.subject)
    else:
        _redis_set(view)
    return view


def consume_challenge(db: Session, challenge_id: uuid.UUID) -> ChallengeView | None:
    """Atomically mark challenge used in Postgres, then delete Redis key."""
    now = _now()
    row = db.get(AuthChallenge, challenge_id)
    if row is None or row.used_at is not None or _aware(row.expires_at) <= now:
        return None
    # Conditional update for concurrency safety
    result = db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge_id,
            AuthChallenge.used_at.is_(None),
            AuthChallenge.expires_at > now,
        )
        .values(used_at=now)
    )
    if int(result.rowcount or 0) != 1:
        db.rollback()
        return None
    db.commit()
    row = db.get(AuthChallenge, challenge_id)
    if row is None:
        return None
    view = ChallengeView.from_row(row)
    _redis_delete(view.purpose, view.subject)
    return view


def cooldown_active(db: Session, purpose: str, subject: str, interval_seconds: int) -> bool:
    """Postgres-only cooldown based on latest created_at for subject+purpose."""
    if interval_seconds <= 0:
        return False
    row = db.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.purpose == purpose, AuthChallenge.subject == subject)
        .order_by(AuthChallenge.created_at.desc())
        .limit(1)
    )
    if row is None:
        return False
    created = _aware(row.created_at)
    return created + timedelta(seconds=interval_seconds) > _now()


def purge_expired(db: Session) -> int:
    now = _now()
    stale_used_before = now - timedelta(days=7)
    result = db.execute(
        delete(AuthChallenge).where(
            (AuthChallenge.expires_at < now)
            | ((AuthChallenge.used_at.is_not(None)) & (AuthChallenge.created_at < stale_used_before))
        )
    )
    db.commit()
    return int(result.rowcount or 0)


def clear_challenges(db: Session, purpose: str, subject: str) -> None:
    now = _now()
    db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.purpose == purpose,
            AuthChallenge.subject == subject,
            AuthChallenge.used_at.is_(None),
        )
        .values(used_at=now)
    )
    db.commit()
    _redis_delete(purpose, subject)


def record_login_failure(db: Session, subject: str) -> ChallengeView:
    active = get_active_challenge(db, PURPOSE_LOGIN_FAIL, subject)
    if active is None:
        return create_challenge(
            db,
            purpose=PURPOSE_LOGIN_FAIL,
            subject=subject,
            code_hash=None,
            ttl_seconds=LOGIN_FAIL_LOCK_SECONDS,
            max_attempts=LOGIN_FAIL_MAX_ATTEMPTS,
            initial_attempts=1,
        )
    return register_failed_attempt(db, active)


def is_login_locked(db: Session, subject: str) -> bool:
    active = get_active_challenge(db, PURPOSE_LOGIN_FAIL, subject)
    if active is None:
        return False
    return active.attempts >= active.max_attempts and not active.is_expired()


def clear_login_failures(db: Session, subject: str) -> None:
    clear_challenges(db, PURPOSE_LOGIN_FAIL, subject)
