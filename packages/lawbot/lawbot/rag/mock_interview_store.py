"""Mock-interview bank retriever — isolated from chat search_kb."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from lawbot.knowledge.importers import MAIN_SEARCH_DOMAIN_BLOCKLIST
from lawbot.paths import resolve_rag_memory_dir
from lawbot.rag.factory import RetrieverSettings, build_isolated_memory_retriever

logger = logging.getLogger(__name__)

DEFAULT_MOCK_INTERVIEW_DIR = "data/rag_memory_mock_interview"
MOCK_INTERVIEW_DOMAIN = "mock_interview"

assert MOCK_INTERVIEW_DOMAIN in MAIN_SEARCH_DOMAIN_BLOCKLIST


def resolve_mock_interview_dir(explicit: str | None = None) -> str:
    raw = (explicit or os.environ.get("RAG_MOCK_INTERVIEW_DIR") or DEFAULT_MOCK_INTERVIEW_DIR).strip()
    return str(resolve_rag_memory_dir(raw))


@lru_cache(maxsize=4)
def get_mock_interview_retriever(
    memory_dir: str = "",
    *,
    embedding_mode: str = "auto",
    embedding_model: str = "",
    embedding_api_key: str = "",
    embedding_api_base: str = "",
    embedding_dim: int = 384,
):
    """Process-cached retriever bound to the mock-interview disk index only."""
    dir_ = resolve_mock_interview_dir(memory_dir or None)
    settings = RetrieverSettings(
        mode="memory",
        memory_dir=dir_,
        embedding_mode=embedding_mode or "auto",
        embedding_model=embedding_model or "",
        embedding_api_key=embedding_api_key or "",
        embedding_api_base=embedding_api_base or None,
        embedding_dim=int(embedding_dim or 384),
    )
    logger.info("building mock interview retriever dir=%s", dir_)
    return build_isolated_memory_retriever(settings)


def clear_mock_interview_retriever_cache() -> None:
    get_mock_interview_retriever.cache_clear()


def search_mock_interview(
    query: str,
    *,
    top_k: int = 5,
    track: str | None = None,
    memory_dir: str = "",
    embedding_mode: str = "auto",
    embedding_model: str = "",
    embedding_api_key: str = "",
    embedding_api_base: str = "",
    embedding_dim: int = 384,
) -> list[dict[str, Any]]:
    """Retrieve from mock bank only. Optional track filter on citation.category / meta."""
    retriever = get_mock_interview_retriever(
        memory_dir,
        embedding_mode=embedding_mode,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        embedding_api_base=embedding_api_base,
        embedding_dim=embedding_dim,
    )
    chunks = retriever.retrieve(
        query,
        top_k=max(top_k * 3, top_k),
        domains=[MOCK_INTERVIEW_DOMAIN],
    )
    out: list[dict[str, Any]] = []
    want = (track or "").strip().lower()
    for ch in chunks:
        c = ch.citation
        domain = c.domain or ""
        if domain in MAIN_SEARCH_DOMAIN_BLOCKLIST and domain != MOCK_INTERVIEW_DOMAIN:
            continue
        if domain != MOCK_INTERVIEW_DOMAIN:
            continue
        cat = str(c.category or c.article_no or "").lower()
        if want and want not in cat and want not in str(c.law_name or "").lower():
            # Prefer track match; keep unscored skip
            continue
        out.append(
            {
                "source_id": c.source_id,
                "title": c.law_name,
                "text": c.text,
                "domain": domain,
                "category": c.category,
                "score": float(getattr(ch, "score", 0.0) or 0.0),
            }
        )
        if len(out) >= top_k:
            break
    # If track filter emptied results, fall back to unfiltered mock domain hits
    if want and not out:
        for ch in chunks:
            c = ch.citation
            if (c.domain or "") != MOCK_INTERVIEW_DOMAIN:
                continue
            out.append(
                {
                    "source_id": c.source_id,
                    "title": c.law_name,
                    "text": c.text,
                    "domain": c.domain,
                    "category": c.category,
                    "score": float(getattr(ch, "score", 0.0) or 0.0),
                }
            )
            if len(out) >= top_k:
                break
    return out
