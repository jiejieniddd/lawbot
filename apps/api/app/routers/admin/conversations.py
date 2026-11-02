from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db, require_admin
from lawbot.db.models import Conversation, Message, User
from lawbot.domain.schemas import ConversationOut, MessageOut

router = APIRouter(prefix="/conversations", tags=["admin-conversations"])


@router.get("", response_model=list[ConversationOut])
def list_all_conversations(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Conversation]:
    return list(
        db.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(200)).all()
    )


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages_admin(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[Message]:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).all()
    )
