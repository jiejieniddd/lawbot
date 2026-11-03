from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import get_current_user, get_db, get_request_id
from app.retriever_dep import get_retriever
from lawbot.agent.graph import run_agent_stream
from lawbot.db.models import Conversation, Message, User
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import ChatEvent, ChatRequest, MessageRole
from lawbot.llm.client import resolve_provider_credentials

router = APIRouter(tags=["v1-chat"])


def _sse(event: ChatEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


@router.post("/chat")
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> StreamingResponse:
    conv = db.get(Conversation, body.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

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
    credentials = resolve_provider_credentials(
        db,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    retriever = get_retriever()

    def event_stream() -> Iterator[str]:
        answer_parts: list[str] = []
        citations: list[dict] = []
        blocked = False
        final_state = None

        for item in run_agent_stream(
            body.content,
            request_id,
            retriever=retriever,
            credentials=credentials,
            top_k=settings.retriever_top_k,
        ):
            if isinstance(item, ChatEvent):
                if item.type == "token":
                    answer_parts.append(item.data.get("text", ""))
                elif item.type == "citation":
                    citations.append(item.data)
                elif item.type == "error":
                    blocked = True
                yield _sse(item)
            else:
                final_state = item

        if blocked or final_state is None:
            return

        full = "".join(answer_parts) or final_state.get("answer") or ""
        factory = get_sessionmaker(database_url)
        session = factory()
        try:
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
