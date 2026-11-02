from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from lawbot.db.models import Conversation, Message, User
from lawbot.domain.schemas import ConversationCreate, ConversationOut, MessageOut

router = APIRouter(prefix="/conversations", tags=["v1-conversations"])


@router.post("", response_model=ConversationOut)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conv = Conversation(user_id=user.id, title=body.title or "新咨询")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Conversation]:
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return list(rows)


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conv


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Message]:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    return list(rows)
