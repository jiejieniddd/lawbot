from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_db, require_permission
from lawbot.db.models import Conversation, KnowledgeDocument, Message, User
from lawbot.domain.schemas import StatsOverview, UserRole

router = APIRouter(prefix="/stats", tags=["admin-stats"])


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
