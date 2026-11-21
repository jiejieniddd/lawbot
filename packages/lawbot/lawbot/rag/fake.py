from __future__ import annotations

from lawbot.domain.schemas import Citation
from lawbot.rag.base import RetrievedChunk


class FakeRetriever:
    """Deterministic stub retriever for skeleton builds (CareerBot interview samples)."""

    FAKE_DOCS: list[Citation] = [
        Citation(
            law_name="后端常考：HTTP 与 RESTful",
            article_no="interview_qa",
            text="常见问题包括状态码含义、幂等性、鉴权方式（JWT/Session）以及如何设计资源路径。",
            source_id="fake-interview-backend-http",
            category="interview_qa",
            domain="interview_qa",
            source_url=None,
            status=None,
        ),
        Citation(
            law_name="Python 后端：并发与 GIL",
            article_no="interview_qa",
            text="解释 GIL 对多线程 CPU 密集任务的影响，并对比多进程、异步 IO 适用场景。",
            source_id="fake-interview-python-gil",
            category="interview_qa",
            domain="interview_qa",
        ),
        Citation(
            law_name="FastAPI dependency injection",
            article_no="tech_docs",
            text="FastAPI Depends 用于注入共享资源（DB session、当前用户），便于测试与复用。",
            source_id="fake-tech-fastapi-depends",
            category="framework",
            domain="tech_docs",
        ),
    ]

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        *,
        domains: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        q = query.lower()
        allowed = {d for d in (domains or []) if d}
        scored: list[RetrievedChunk] = []
        for doc in self.FAKE_DOCS:
            if allowed and (doc.domain or "") not in allowed:
                continue
            score = 0.5
            if any(k in q for k in ("后端", "backend", "python", "fastapi", "http")):
                if "backend" in (doc.source_id or "") or "python" in (doc.source_id or "") or "fastapi" in (
                    doc.source_id or ""
                ):
                    score = 1.0
            elif any(k in q for k in ("面试", "常考", "求职")):
                if doc.domain == "interview_qa":
                    score = 0.9
            scored.append(RetrievedChunk(citation=doc, score=score))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
