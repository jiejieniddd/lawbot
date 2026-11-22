"""Mock interview sessions — separate from chat graph."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_current_user, get_db
from app.retriever_dep import get_retriever
from app.services import interview as interview_svc
from lawbot.db.models import User
from lawbot.llm.client import resolve_provider_credentials

router = APIRouter(prefix="/interview", tags=["interview"])


class CreateSessionBody(BaseModel):
    question_count: Literal[5, 8] = 5
    target_role: str = Field(default="", max_length=255)
    """Per-session job title/direction — entered on interview prep, not from settings."""
    jd_text: str = Field(default="", max_length=50_000)
    """Optional JD paste for this session only (not persisted to user_jds)."""


class AnswerBody(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


@router.post("/sessions")
def create_interview_session(
    body: CreateSessionBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    session = interview_svc.create_session(
        db,
        user_id=user.id,
        question_count=int(body.question_count),
        target_role=body.target_role.strip(),
        jd_text=body.jd_text.strip(),
        retriever=get_retriever(),
    )
    return interview_svc.session_public(session)


@router.get("/sessions/{session_id}")
def get_interview_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    session = interview_svc.get_session_for_user(db, session_id, user.id)
    return interview_svc.session_public(session, include_report=session.status == "completed")


@router.post("/sessions/{session_id}/answer")
def answer_interview_turn(
    session_id: uuid.UUID,
    body: AnswerBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    credentials = resolve_provider_credentials(
        db,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    return interview_svc.submit_answer(
        db,
        session_id=session_id,
        user_id=user.id,
        answer=body.answer,
        credentials=credentials,
        retriever=get_retriever(),
    )


@router.get("/sessions/{session_id}/report")
def get_interview_report(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return interview_svc.get_report(db, session_id=session_id, user_id=user.id)
