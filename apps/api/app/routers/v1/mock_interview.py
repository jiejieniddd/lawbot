"""Mock oral-interview bank search — isolated from chat search_kb."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.deps import get_current_user
from app.services.embedding_config import env_defaults_from_settings
from lawbot.db.models import User
from lawbot.db.session import get_sessionmaker
from lawbot.knowledge.embedding_settings import resolve_embedding_config
from lawbot.rag.mock_interview_store import search_mock_interview

router = APIRouter(tags=["mock-interview"])


class MockInterviewSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    track: str | None = None


class MockInterviewHit(BaseModel):
    source_id: str
    title: str | None = None
    text: str
    domain: str | None = None
    category: str | None = None
    score: float = 0.0


class MockInterviewSearchResponse(BaseModel):
    hits: list[MockInterviewHit]
    memory_dir: str


@router.post("/mock-interview/search", response_model=MockInterviewSearchResponse)
def mock_interview_search(
    body: MockInterviewSearchRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> MockInterviewSearchResponse:
    _ = user
    factory = get_sessionmaker(settings.database_url)
    db = factory()
    try:
        resolved = resolve_embedding_config(db, env_defaults_from_settings(settings))
    finally:
        db.close()
    emb_mode = resolved.effective_mode if resolved.mode == "auto" else resolved.mode
    hits = search_mock_interview(
        body.query,
        top_k=body.top_k,
        track=body.track,
        memory_dir=settings.rag_mock_interview_dir,
        embedding_mode=emb_mode or "auto",
        embedding_model=resolved.embedding_model or "",
        embedding_api_key=resolved.api_key or "",
        embedding_api_base=resolved.api_base or "",
        embedding_dim=int(resolved.embedding_dim or 384),
    )
    return MockInterviewSearchResponse(
        hits=[MockInterviewHit(**h) for h in hits],
        memory_dir=settings.rag_mock_interview_dir,
    )
