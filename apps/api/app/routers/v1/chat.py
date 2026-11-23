from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import get_current_user, get_db, get_request_id
from app.retriever_dep import get_retriever
from lawbot.agent.graph import run_agent_stream
from lawbot.agent.memory_store import (
    get_memory_store,
    put_preference_memories,
    search_user_memories,
)
from lawbot.agent.preferences import extract_province, load_user_preference, upsert_user_preference
from lawbot.db.models import Conversation, Message, User
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import ChatEvent, ChatRequest, MessageRole
from lawbot.llm.client import resolve_provider_credentials

logger = logging.getLogger(__name__)
router = APIRouter(tags=["v1-chat"])

# Recent turns for prompt only (slots come from checkpointer thread).
_RECENT_HISTORY_LIMIT = 6


def _sse(event: ChatEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


def _load_recent_history(db: Session, conversation_id: object, *, limit: int = _RECENT_HISTORY_LIMIT) -> list[dict[str, str]]:
    """Load last N messages for prompt / 请补充 detection — not a second slot source."""
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(max(1, limit))
        ).all()
    )
    rows.reverse()
    out: list[dict[str, str]] = []
    for row in rows:
        role = "user" if row.role == MessageRole.USER else "assistant"
        content = (row.content or "").strip()
        if content:
            out.append({"role": role, "content": content})
    return out


@router.post("/chat")
def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:
    received_at = getattr(request.state, "received_at", time.monotonic())
    timing = logging.getLogger("lawbot.timing")
    conv = db.get(Conversation, body.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Load history before inserting this turn so N includes prior turns only.
    recent_history = _load_recent_history(db, conv.id)

    user_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.USER,
        content=body.content,
        citations=[],
        request_id=request_id,
    )
    db.add(user_msg)
    if conv.title == "新咨询":
        conv.title = body.content[:80]
    db.commit()

    conversation_id = conv.id
    settings = get_settings()
    database_url = settings.database_url
    province = extract_province(body.content)
    pref = load_user_preference(db, user.id)
    if province or (pref and pref.case_domain):
        if province:
            upsert_user_preference(db, user_id=user.id, province=province)
            pref = load_user_preference(db, user.id)
    province_hint = province or (pref.province if pref else None)
    credentials = resolve_provider_credentials(
        db,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    retriever = get_retriever()

    active_resume: dict | None = None
    try:
        from app.services.resumes import get_active_resume, resume_to_dict

        resume_row = get_active_resume(db, user.id)
        if resume_row is not None and resume_row.parse_status == "ready":
            active_resume = resume_to_dict(resume_row)
    except Exception:
        logger.exception("active resume load failed; continuing without resume")

    active_jd: dict | None = None
    try:
        from app.services.jds import get_active_jd, jd_to_dict

        jd_row = get_active_jd(db, user.id)
        if jd_row is not None and jd_row.parse_status == "ready":
            active_jd = jd_to_dict(jd_row)
    except Exception:
        logger.exception("active JD load failed; continuing without JD")

    store_facts: list[dict] = []
    try:
        mem_store = get_memory_store(database_url)
        put_preference_memories(
            mem_store,
            user_id=str(user.id),
            province=province_hint,
            case_domain=pref.case_domain if pref else None,
        )
        store_facts = search_user_memories(
            mem_store,
            user_id=str(user.id),
            query=body.content,
            limit=4,
        )
    except Exception:
        logger.exception("memory store read failed; continuing without store facts")

    def event_stream() -> Iterator[str]:
        first_token = False
        timing.info("agent_timing request_id=%s stage=request_setup elapsed_ms=%.2f", request_id, (time.monotonic() - received_at) * 1000)
        answer_parts: list[str] = []
        citations: list[dict] = []
        blocked = False
        final_state = None

        try:
            for item in run_agent_stream(
                body.content,
                request_id,
                retriever=retriever,
                credentials=credentials,
                top_k=settings.retriever_top_k,
                # Prompt assist + 请补充 detection; slots authoritative via checkpointer.
                history=recent_history or None,
                max_followups=settings.agent_max_followups,
                min_retrieve_score=settings.retrieve_min_score,
                conversation_id=str(conversation_id),
                database_url=database_url,
                province_hint=province_hint,
                user_id=str(user.id),
                store_facts=store_facts,
                active_resume=active_resume,
                active_jd=active_jd,
            ):
                if isinstance(item, ChatEvent):
                    if item.type == "token":
                        if not first_token and item.data.get("text"):
                            first_token = True
                            timing.info("agent_timing request_id=%s stage=first_token elapsed_ms=%.2f", request_id, (time.monotonic() - received_at) * 1000)
                        answer_parts.append(item.data.get("text", ""))
                    elif item.type == "citation":
                        citations.append(item.data)
                    elif item.type == "error":
                        blocked = True
                    yield _sse(item)
                else:
                    final_state = item
        except Exception:
            logger.exception("chat stream failed request_id=%s", request_id)
            yield _sse(
                ChatEvent.error(request_id, "generation_failed", "生成失败，请稍后重试")
            )
            return

        finally:
            timing.info("agent_timing request_id=%s stage=response_generation elapsed_ms=%.2f first_token=%s", request_id, (time.monotonic() - received_at) * 1000, first_token)

        if blocked or final_state is None:
            return

        full = "".join(answer_parts) or final_state.get("answer") or ""
        factory = get_sessionmaker(database_url)
        session = factory()
        try:
            domain = final_state.get("case_type")
            if domain and domain != "general":
                upsert_user_preference(
                    session,
                    user_id=user.id,
                    case_domain=str(domain),
                    province=province or None,
                )
            try:
                mem_store = get_memory_store(database_url)
                put_preference_memories(
                    mem_store,
                    user_id=str(user.id),
                    province=province or (final_state.get("province") or None),
                    case_domain=str(domain) if domain else None,
                )
            except Exception:
                logger.exception("memory store write failed after chat")
            assistant = Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=full,
                citations=citations,
                request_id=request_id,
            )
            session.add(assistant)
            session.commit()
            session.refresh(assistant)
            yield _sse(
                ChatEvent.done(
                    request_id,
                    message_id=assistant.id,
                    conversation_id=conversation_id,
                )
            )
        finally:
            session.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
