from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from lawbot.domain.schemas import Citation


class RetrievedChunk(BaseModel):
    citation: Citation
    score: float = 1.0


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        """Return ranked citation chunks for a query."""
