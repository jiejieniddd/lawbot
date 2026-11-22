from __future__ import annotations

from pydantic import BaseModel, Field


class TurnScore(BaseModel):
    score: int = Field(ge=0, le=100, default=60)
    feedback: str = ""
    clarity: int = Field(ge=0, le=100, default=60)
    depth: int = Field(ge=0, le=100, default=60)
    relevance: int = Field(ge=0, le=100, default=60)

    def dimensions_dict(self) -> dict[str, int]:
        return {
            "clarity": int(self.clarity),
            "depth": int(self.depth),
            "relevance": int(self.relevance),
        }


class TurnBrief(BaseModel):
    seq: int
    question: str
    score: int = 0
    feedback: str = ""


class GapItem(BaseModel):
    skill: str
    suggestion: str = ""


class InterviewReport(BaseModel):
    total_score: int = Field(ge=0, le=100, default=0)
    dimension_averages: dict[str, int] = Field(default_factory=dict)
    turns: list[TurnBrief] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    advice: str = ""
    disclaimer: str = "AI 初评仅供参考，不构成录用承诺或官方认证。"
    target_role: str = ""
    has_resume: bool = False
    resume_note: str = ""

    def model_dump_public(self) -> dict:
        return self.model_dump()


class DraftQuestion(BaseModel):
    question: str
    reference_text: str = ""
