from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.deps import require_admin
from app.retriever_dep import get_retriever
from lawbot.db.models import User
from lawbot.domain.schemas import Citation

router = APIRouter(prefix="/knowledge", tags=["admin-knowledge-search"])


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchResponse(BaseModel):
    query: str
    results: list[Citation] = Field(default_factory=list)


def _run_search(q: str, top_k: int | None, settings: Settings) -> SearchResponse:
    retriever = get_retriever()
    k = top_k or settings.retriever_top_k
    chunks = retriever.retrieve(q, top_k=k)
    return SearchResponse(query=q, results=[c.citation for c in chunks])


@router.get("/search", response_model=SearchResponse)
def trial_search_get(
    q: str = Query(min_length=1, max_length=500),
    top_k: int | None = Query(default=None, ge=1, le=20),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    return _run_search(q, top_k, settings)


@router.post("/search", response_model=SearchResponse)
def trial_search_post(
    body: SearchRequest,
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    return _run_search(body.q, body.top_k, settings)
