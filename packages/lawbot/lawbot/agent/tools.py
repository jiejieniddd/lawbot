"""Career-path tools. Handlers run only after Pydantic validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from lawbot.domain.job_match_schema import JobMatchReport
from lawbot.domain.resume_schema import ResumeProfile
from lawbot.domain.schemas import CAREER_DISCLAIMER
from lawbot.knowledge.importers import MAIN_SEARCH_DOMAIN_BLOCKLIST
from lawbot.paths import repo_root
from lawbot.rag.base import Retriever

EXCLUSIVE_TOOLS = frozenset({"ask_clarification", "search_kb"})


class SearchKbArgs(BaseModel):
    query: str = Field(min_length=1, description="检索问句（面试题/技术点/技能关键词）")
    top_k: int = Field(ge=1, le=20, default=5, description="返回条数上限")
    domains: list[str] = Field(
        default_factory=list,
        description=(
            "可选 domain 过滤：interview_qa / tech_docs / gotchas / job_skills；"
            "空=主库全域。self_test 永久拦截，勿传入"
        ),
    )


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


class EmitCareerReportArgs(BaseModel):
    direction: str = Field(min_length=1)
    key_points: str = Field(min_length=1)
    advice: str = Field(min_length=1)
    risk: str = Field(min_length=1)


class AnalyzeResumeArgs(BaseModel):
    focus: str = Field(default="skills")


class SkillGapPlanArgs(BaseModel):
    target_role: str = Field(
        default="",
        description="目标岗位/方向；空则用简历 intent 或通用后端关键词",
    )
    top_k: int = Field(ge=1, le=10, default=5, description="检索条数")


class InterviewFollowupArgs(BaseModel):
    topic: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=5, default=3)


class MatchJobArgs(BaseModel):
    jd_text: str = Field(
        default="",
        description="JD 原文；空则使用 ToolContext.active_jd 已上传/粘贴内容",
    )
    target_role: str = Field(default="", description="可选目标岗位标签，辅助检索")
    top_k: int = Field(ge=1, le=10, default=5, description="市场/面试相关检索条数")


class KbHit(BaseModel):
    law_name: str  # title (compat)
    article_no: str  # category (compat)
    text: str
    source_id: str
    score: float
    domain: str | None = None
    category: str | None = None
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
    active_resume: dict[str, Any] | None = None
    active_jd: dict[str, Any] | None = None


_ROLE_SKILL_MAP_CACHE: dict[str, list[str]] | None = None


def load_role_skill_map(path: str | None = None) -> dict[str, list[str]]:
    """Load direction → top skills map (never embeds FairCV)."""
    global _ROLE_SKILL_MAP_CACHE
    if _ROLE_SKILL_MAP_CACHE is not None and path is None:
        return _ROLE_SKILL_MAP_CACHE
    import json
    from pathlib import Path

    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.append(repo_root() / "data" / "market" / "role_skill_map.json")
    for p in candidates:
        if p.is_file():
            raw = json.loads(p.read_text(encoding="utf-8"))
            roles = raw.get("roles") if isinstance(raw, dict) else raw
            if isinstance(roles, dict):
                mapping = {
                    str(k): [str(x) for x in (v or []) if str(x).strip()]
                    for k, v in roles.items()
                }
                if path is None:
                    _ROLE_SKILL_MAP_CACHE = mapping
                return mapping
    return {}


def _jd_text_from_ctx(ctx: ToolContext, explicit: str = "") -> str:
    if (explicit or "").strip():
        return explicit.strip()
    jd = ctx.active_jd or {}
    return str(jd.get("raw_text") or jd.get("text") or jd.get("summary") or "").strip()


def _extract_jd_skills(text: str) -> list[str]:
    from lawbot.knowledge.importers.ai_job_zh import _extract_skills

    return _extract_skills(text or "")


def _market_skills_for_role(role: str) -> list[str]:
    mapping = load_role_skill_map()
    if not mapping:
        return []
    role_l = (role or "").strip().lower()
    if not role_l:
        return []
    exact = next((skills for key, skills in mapping.items() if key.lower() == role_l), None)
    if exact is not None:
        return list(exact)
    matches = [
        (len(key), skills)
        for key, skills in mapping.items()
        if len(key) >= 3 and (key.lower() in role_l or (len(role_l) >= 3 and role_l in key.lower()))
    ]
    if matches:
        return list(max(matches, key=lambda item: item[0])[1])
    for token in ("算法", "后端", "前端", "全栈", "测试", "安全", "数据", "运维", "移动端", "视觉", "nlp", "slam", "大模型"):
        if token in role_l:
            aligned = next((skills for key, skills in mapping.items() if token in key.lower()), None)
            if aligned is not None:
                return list(aligned)
    return []


def format_career_report(args: EmitCareerReportArgs) -> str:
    return (
        f"## 方向建议\n\n{args.direction}\n\n"
        f"## 要点\n\n{args.key_points}\n\n"
        f"## 建议\n\n{args.advice}\n\n"
        f"## 注意\n\n{args.risk}\n\n"
        f"## 声明\n\n{CAREER_DISCLAIMER}"
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


def _search_kb(args: SearchKbArgs, ctx: ToolContext) -> list[dict[str, Any]]:
    if ctx.retriever is None:
        raise RuntimeError("search_kb requires a retriever")
    domains = [d for d in args.domains if d and d not in MAIN_SEARCH_DOMAIN_BLOCKLIST] or None
    try:
        chunks = ctx.retriever.retrieve(args.query, top_k=args.top_k, domains=domains)  # type: ignore[call-arg]
    except TypeError:
        chunks = ctx.retriever.retrieve(args.query, top_k=args.top_k)
        if domains:
            chunks = [c for c in chunks if (c.citation.domain or "") in set(domains)]
    hits: list[dict[str, Any]] = []
    for chunk in chunks:
        citation = chunk.citation
        domain = citation.domain
        if domain in MAIN_SEARCH_DOMAIN_BLOCKLIST:
            continue
        hits.append(
            KbHit(
                law_name=citation.law_name,
                article_no=citation.article_no,
                text=citation.text,
                source_id=citation.source_id,
                score=float(chunk.score),
                domain=domain,
                category=citation.category,
                effective_date=citation.effective_date,
                status=citation.status,
                jurisdiction=citation.jurisdiction,
            ).model_dump()
        )
    return hits


def _ask_clarification(args: AskClarificationArgs, ctx: ToolContext) -> str:
    del ctx
    return args.question


def _emit_career_report(args: EmitCareerReportArgs, ctx: ToolContext) -> str:
    del ctx
    return format_career_report(args)


def _profile_from_ctx(ctx: ToolContext) -> ResumeProfile:
    data = ctx.active_resume or {}
    structured = data.get("structured") if isinstance(data.get("structured"), dict) else data
    if not isinstance(structured, dict):
        structured = {}
    # Prefer nested structured; fall back to top-level skills/intent from API dict
    if not structured.get("skills") and data.get("skills"):
        structured = {**structured, "skills": data.get("skills"), "intent": data.get("intent") or ""}
    return ResumeProfile.from_dict(structured)


def _analyze_resume(args: AnalyzeResumeArgs, ctx: ToolContext) -> dict[str, Any]:
    profile = _profile_from_ctx(ctx)
    skills = list(profile.skills)
    return {
        "focus": args.focus,
        "skills": skills,
        "intent": profile.intent,
        "projects": [p.model_dump() for p in profile.projects[:5]],
        "education": [e.model_dump() for e in profile.education[:3]],
        "summary": profile.prompt_block(),
        "has_resume": bool(skills or profile.summary or profile.intent),
    }


def _skill_gap_plan(args: SkillGapPlanArgs, ctx: ToolContext) -> dict[str, Any]:
    profile = _profile_from_ctx(ctx)
    skills = list(profile.skills)
    target = (args.target_role or profile.intent or "后端开发").strip()
    market = _market_skills_for_role(target)
    skill_l = {s.lower() for s in skills}
    map_gaps = [s for s in market if s.lower() not in skill_l]
    query = f"{target} 技能 要求 {' '.join(skills[:8])}".strip()
    kb_hits: list[dict[str, Any]] = []
    if ctx.retriever is not None:
        kb_hits = _search_kb(
            SearchKbArgs(
                query=query,
                top_k=args.top_k,
                domains=["job_skills", "tech_docs", "interview_qa"],
            ),
            ctx,
        )
    gaps = list(map_gaps)
    for hit in kb_hits:
        title = str(hit.get("law_name") or "")
        if title and not any(s.lower() in title.lower() for s in skills) and title not in gaps:
            gaps.append(title)
    used_map = bool(market)
    return {
        "target_role": target,
        "current_skills": skills,
        "market_skills": market,
        "suggested_gaps": gaps[:8],
        "kb_hits": kb_hits,
        "role_skill_map_used": used_map,
        "plan": (
            f"目标方向：{target}。当前技能：{'、'.join(skills) or '（简历未解析到技能）'}。"
            + (
                f"市场地图 Top 技能：{'、'.join(market[:8])}。"
                if market
                else "（未加载 role_skill_map，仅用检索。）"
            )
            + f"建议优先补齐：{'、'.join(gaps[:5]) or '对照 JD 再细化'}。"
        ),
        "skill_set_lower": list(skill_l),
    }


def _match_job(args: MatchJobArgs, ctx: ToolContext) -> dict[str, Any]:
    profile = _profile_from_ctx(ctx)
    resume_skills = list(profile.skills)
    jd_text = _jd_text_from_ctx(ctx, args.jd_text)
    jd_skills = _extract_jd_skills(jd_text)
    target = (args.target_role or profile.intent or "").strip()
    if not target and jd_text:
        # first line / first 40 chars as rough role
        target = jd_text.strip().splitlines()[0][:40]
    market = _market_skills_for_role(target)
    required = []
    for s in jd_skills + market:
        if s not in required:
            required.append(s)
    resume_l = {s.lower() for s in resume_skills}
    matched = [s for s in required if s.lower() in resume_l]
    gaps = [s for s in required if s.lower() not in resume_l]
    score = (len(matched) / len(required)) if required else (0.35 if resume_skills else 0.0)
    score = max(0.0, min(1.0, float(score)))

    kb_hits: list[dict[str, Any]] = []
    interview_prep: list[str] = []
    if ctx.retriever is not None:
        q = f"{target} {' '.join((jd_skills or resume_skills)[:6])}".strip() or "算法工程师"
        kb_hits = _search_kb(
            SearchKbArgs(query=q, top_k=args.top_k, domains=["job_skills"]),
            ctx,
        )
        follow = _search_kb(
            SearchKbArgs(
                query=q,
                top_k=min(3, args.top_k),
                domains=["interview_qa", "gotchas"],
            ),
            ctx,
        )
        for hit in follow:
            title = str(hit.get("law_name") or "").strip()
            if title:
                interview_prep.append(f"准备讲解：{title[:60]}")
        if not interview_prep:
            interview_prep = [
                "准备与缺口技能相关的学习/项目故事",
                "用 STAR 讲清最近一个相关项目",
            ]

    report = JobMatchReport(
        match_score=round(score, 3),
        matched=matched[:10],
        gaps=gaps[:10],
        resume_rewrite=[
            f"在技能栏突出：{'、'.join(matched[:5]) or '与 JD 重合的关键词'}",
            f"针对缺口补充学习/项目表述：{'、'.join(gaps[:4]) or '按 JD 补一条可验证经历'}",
            "量化项目结果（性能、覆盖率、业务指标），避免空泛形容词",
        ],
        interview_prep=interview_prep[:6],
        manual_apply_checklist=[
            "人工核对简历与 JD 关键词一致后再投递",
            "按官方渠道手工投递并记录进度",
            "禁止招聘站爬虫、验证码绕过或无人值守自动投递",
        ],
        citations=kb_hits[:5],
        target_role=target,
        jd_skills=jd_skills,
        resume_skills=resume_skills,
        market_skills=market[:12],
        note="匹配基于简历槽位、JD 文本、role_skill_map 与 job_skills 检索；仅供参考。",
    )
    payload = report.model_dump()
    payload["markdown"] = report.to_markdown()
    payload["role_skill_map_used"] = bool(market)
    return payload


def _interview_followup(args: InterviewFollowupArgs, ctx: ToolContext) -> dict[str, Any]:
    if ctx.retriever is None:
        raise RuntimeError("interview_followup requires a retriever")
    hits = _search_kb(
        SearchKbArgs(query=args.topic, top_k=args.top_k, domains=["gotchas"]),
        ctx,
    )
    directions: list[str] = []
    for hit in hits[: args.top_k]:
        title = str(hit.get("law_name") or "").strip()
        text = str(hit.get("text") or "").strip()
        snippet = (title or text[:80]).strip()
        if snippet:
            directions.append(f"追问方向：{snippet}")
    if not directions:
        directions = [
            f"追问方向：围绕「{args.topic}」的边界条件与失败案例",
            f"追问方向：请举例说明「{args.topic}」在项目中的取舍",
            f"追问方向：若线上出现相关故障，你会如何排查「{args.topic}」",
        ]
    return {"topic": args.topic, "directions": directions[:3], "kb_hits": hits}


ToolHandler = Callable[[Any, ToolContext], Any]


REGISTRY: dict[str, tuple[type[BaseModel], ToolHandler]] = {
    "search_kb": (SearchKbArgs, _search_kb),
    "ask_clarification": (AskClarificationArgs, _ask_clarification),
    "emit_career_report": (EmitCareerReportArgs, _emit_career_report),
    "analyze_resume": (AnalyzeResumeArgs, _analyze_resume),
    "skill_gap_plan": (SkillGapPlanArgs, _skill_gap_plan),
    "interview_followup": (InterviewFollowupArgs, _interview_followup),
    "match_job": (MatchJobArgs, _match_job),
    # Legacy aliases (tests / old traces)
    "search_laws": (SearchKbArgs, _search_kb),
    "emit_legal_report": (EmitCareerReportArgs, _emit_career_report),
}


def execute_tool(name: str, raw_args: Any, ctx: ToolContext) -> ToolOutcome:
    spec = REGISTRY.get(name)
    if spec is None:
        _record(ctx, name=name, arguments=raw_args, ok=False, error="unknown_tool")
        return ToolOutcome(ok=False, name=name, error="unknown_tool")
    model, handler = spec
    # Map legacy emit_legal_report field names if present
    if name == "emit_legal_report" and isinstance(raw_args, dict):
        raw_args = {
            "direction": raw_args.get("direction") or raw_args.get("legal_basis") or "",
            "key_points": raw_args.get("key_points") or raw_args.get("analysis") or "",
            "advice": raw_args.get("advice") or "",
            "risk": raw_args.get("risk") or "",
        }
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
    """Run one career turn. Clarification and retrieval cannot both run."""
    names = [name for name, _raw in proposals]
    exclusive = {"ask_clarification", "search_kb", "search_laws"}
    if "ask_clarification" in names and (("search_kb" in names) or ("search_laws" in names)):
        for name, raw in proposals:
            if name in exclusive:
                _record(
                    ctx,
                    name=name,
                    arguments=raw,
                    ok=False,
                    error="mutually_exclusive",
                )
        return []
    return [execute_tool(name, raw, ctx) for name, raw in proposals]


# Back-compat exports
SearchLawsArgs = SearchKbArgs
EmitLegalReportArgs = EmitCareerReportArgs
LawHit = KbHit
format_legal_report = format_career_report
