from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, ColumnElement, cast, func, select
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from lawbot.db.models import Conversation, KnowledgeDocument, Message, User
from lawbot.domain.schemas import StatsOverview, StatsSeries, StatsSeriesPoint, UserRole

router = APIRouter(prefix="/stats", tags=["admin-stats"])

_ALLOWED_DAYS = frozenset({7, 14, 30})


def _utc_day_expr(column: ColumnElement[Any], dialect_name: str) -> ColumnElement[Any]:
    """Bucket timestamp into a UTC calendar day (portable across Postgres / SQLite)."""
    if dialect_name == "postgresql":
        return cast(func.timezone("UTC", column), Date)
    # SQLite tests: date() extracts the calendar date from stored ISO timestamps.
    return func.date(column)


def _counts_by_day(
    db: Session,
    column: ColumnElement[Any],
    *,
    start: datetime,
    end: datetime,
    where: ColumnElement[bool] | None = None,
) -> dict[str, int]:
    dialect = db.get_bind().dialect.name
    day = _utc_day_expr(column, dialect)
    stmt = (
        select(day.label("d"), func.count().label("n"))
        .where(column >= start, column < end)
        .group_by(day)
    )
    if where is not None:
        stmt = stmt.where(where)
    out: dict[str, int] = {}
    for d, n in db.execute(stmt).all():
        if d is None:
            continue
        if isinstance(d, datetime):
            key = d.date().isoformat()
        elif isinstance(d, date):
            key = d.isoformat()
        else:
            key = str(d)[:10]
        out[key] = int(n)
    return out


@router.get("/overview", response_model=StatsOverview)
def overview(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_permission("stats:read")),
) -> StatsOverview:
    users = db.scalar(select(func.count()).select_from(User)) or 0
    end_users = (
        db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.USER)) or 0
    )
    admins = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATOR]))
        )
        or 0
    )
    conversations = db.scalar(select(func.count()).select_from(Conversation)) or 0
    messages = db.scalar(select(func.count()).select_from(Message)) or 0
    docs = db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0
    return StatsOverview(
        users=users,
        end_users=end_users,
        admins=admins,
        conversations=conversations,
        messages=messages,
        knowledge_documents=docs,
    )


@router.get("/series", response_model=StatsSeries)
def series(
    days: int = Query(14, description="UTC day window length; one of 7, 14, 30"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_permission("stats:read")),
) -> StatsSeries:
    """Daily new end-users / conversations / messages. Buckets are UTC calendar days."""
    if days not in _ALLOWED_DAYS:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="days must be 7, 14, or 30")

    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=days - 1)
    start_dt = datetime(start_day.year, start_day.month, start_day.day, tzinfo=timezone.utc)
    end_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)

    users_by = _counts_by_day(
        db, User.created_at, start=start_dt, end=end_dt, where=User.role == UserRole.USER
    )
    conv_by = _counts_by_day(db, Conversation.created_at, start=start_dt, end=end_dt)
    msg_by = _counts_by_day(db, Message.created_at, start=start_dt, end=end_dt)

    points: list[StatsSeriesPoint] = []
    for i in range(days):
        d = (start_day + timedelta(days=i)).isoformat()
        points.append(
            StatsSeriesPoint(
                date=d,
                new_end_users=users_by.get(d, 0),
                new_conversations=conv_by.get(d, 0),
                new_messages=msg_by.get(d, 0),
            )
        )
    return StatsSeries(days=days, bucket="day", timezone="UTC", points=points)
