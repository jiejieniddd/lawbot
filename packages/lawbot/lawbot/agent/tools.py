"""Legal-path tools. Handlers run only after Pydantic validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from lawbot.domain.schemas import LEGAL_DISCLAIMER
from lawbot.rag.base import Retriever

EXCLUSIVE_TOOLS = frozenset({"ask_clarification", "search_laws"})


class SearchLawsArgs(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=20)


class AskClarificationArgs(BaseModel):
    missing_facts: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)

    @field_validator("missing_facts")
    @classmethod
    def _facts_not_blank(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("missing_facts 必须是非空列表")
        return cleaned


class EmitLegalReportArgs(BaseModel):
    legal_basis: str = Field(min_length=1)
    analysis: str = Field(min_length=1)
    advice: str = Field(min_length=1)
    risk: str = Field(min_length=1)


class LawHit(BaseModel):
    law_name: str
    article_no: str
    text: str
    source_id: str
    score: float
    effective_date: str | None = None
    status: str | None = None
    jurisdiction: str | None = None


class ToolOutcome(BaseModel):
    ok: bool
    name: str
    output: Any = None
    error: str | None = None


@dataclass
class ToolContext:
    retriever: Retriever | None = None
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


def format_legal_report(args: EmitLegalReportArgs) -> str:
    return (
        f"## 法律依据\n\n{args.legal_basis}\n\n"
        f"## 分析\n\n{args.analysis}\n\n"
        f"## 建议\n\n{args.advice}\n\n"
        f"## 风险提示\n\n{args.risk}\n\n"
        f"## 免责声明\n\n{LEGAL_DISCLAIMER}"
    )


def _validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in exc.errors():
        payload.append(
            {
                "loc": [str(part) for part in item.get("loc", ())],
                "msg": str(item.get("msg") or ""),
                "type": str(item.get("type") or ""),
            }
        )
    return payload


def _record(
    ctx: ToolContext,
    *,
    name: str,
    arguments: Any,
    ok: bool,
    error: Any = None,
) -> None:
    ctx.tool_trace.append(
        {
            "name": name,
            "arguments": arguments,
            "ok": ok,
            "error": error,
        }
    )


def _search_laws(args: SearchLawsArgs, ctx: ToolContext) -> list[dict[str, Any]]:
    if ctx.retriever is None:
        raise RuntimeError("search_laws requires a retriever")
    chunks = ctx.retriever.retrieve(args.query, top_k=args.top_k)
    hits: list[dict[str, Any]] = []
    for chunk in chunks:
        citation = chunk.citation
        hits.append(
            LawHit(
                law_name=citation.law_name,
                article_no=citation.article_no,
                text=citation.text,
                source_id=citation.source_id,
                score=float(chunk.score),
                effective_date=citation.effective_date,
                status=citation.status,
                jurisdiction=citation.jurisdiction,
            ).model_dump()
        )
    return hits


def _ask_clarification(args: AskClarificationArgs, ctx: ToolContext) -> str:
    del ctx
    return args.question


def _emit_legal_report(args: EmitLegalReportArgs, ctx: ToolContext) -> str:
    del ctx
    return format_legal_report(args)


ToolHandler = Callable[[Any, ToolContext], Any]


REGISTRY: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "search_laws": (SearchLawsArgs, _search_laws),
    "ask_clarification": (AskClarificationArgs, _ask_clarification),
    "emit_legal_report": (EmitLegalReportArgs, _emit_legal_report),
}


def execute_tool(name: str, raw_args: Any, ctx: ToolContext) -> ToolOutcome:
    spec = REGISTRY.get(name)
    if spec is None:
        _record(ctx, name=name, arguments=raw_args, ok=False, error="unknown_tool")
        return ToolOutcome(ok=False, name=name, error="unknown_tool")
    model, handler = spec
    try:
        args = model.model_validate(raw_args)
    except ValidationError as exc:
        _record(
            ctx,
            name=name,
            arguments=raw_args,
            ok=False,
            error=_validation_error(exc),
        )
        return ToolOutcome(ok=False, name=name, error="validation")
    output = handler(args, ctx)
    _record(ctx, name=name, arguments=args.model_dump(), ok=True, error=None)
    return ToolOutcome(ok=True, name=name, output=output)


def execute_legal_turn(
    proposals: list[tuple[str, Any]],
    ctx: ToolContext,
) -> list[ToolOutcome]:
    """Run one legal turn. Clarification and retrieval cannot both run."""
    names = [name for name, _raw in proposals]
    if "ask_clarification" in names and "search_laws" in names:
        for name, raw in proposals:
            if name in EXCLUSIVE_TOOLS:
                _record(
                    ctx,
                    name=name,
                    arguments=raw,
                    ok=False,
                    error="mutually_exclusive",
                )
        return []
    return [execute_tool(name, raw, ctx) for name, raw in proposals]
