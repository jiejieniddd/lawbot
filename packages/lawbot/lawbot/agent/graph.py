from __future__ import annotations

import json
import logging
import re
import time
from functools import wraps
from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from lawbot.agent.citations import (
    format_basis_line,
    needs_unverified_fallback,
    repair_citations,
    strip_internal_ids,
    supported_index,
)
from lawbot.agent.checkpoint import get_checkpointer
from lawbot.agent.preferences import LOCAL_LAW_NOTE, extract_province
from lawbot.agent.self_check import run_self_check
from lawbot.agent.tracing import (
    AgentTracer,
    bind_tracer,
    privacy_summary,
    redact_text,
    reset_tracer,
    trace_step,
)
from lawbot.agent.prompts import (
    ANSWER_SYSTEM_PROMPT,
    AUTO_DELIVER_REFUSAL,
    CASE_TYPE_CLASSIFY_SYSTEM_PROMPT,
    CHITCHAT_SYSTEM_PROMPT,
    CLARIFY_SYSTEM_PROMPT,
    FACTS_SUFFICIENCY_SYSTEM_PROMPT,
    FOLLOWUP_SYSTEM_PROMPT,
    INTENT_CLASSIFY_SYSTEM_PROMPT,
    NO_BASIS_SYSTEM_PROMPT,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    STAGED_SYSTEM_PROMPT,
    build_answer_user_prompt,
    build_case_type_classify_user_prompt,
    build_chitchat_user_prompt,
    build_clarify_user_prompt,
    build_facts_sufficiency_user_prompt,
    build_followup_user_prompt,
    build_intent_classify_user_prompt,
    build_no_basis_user_prompt,
    build_staged_user_prompt,
    build_out_of_scope_user_prompt,
    build_rewrite_user_prompt,
    format_citation_block,
)
from lawbot.agent.tools import ToolContext, execute_tool
from lawbot.domain.schemas import ChatEvent, Citation
from lawbot.llm.client import (
    ProviderCredentials,
    StreamTruncatedError,
    complete_text,
    complete_text_stream,
    get_llm_aux_timeout_seconds,
)
from lawbot.rag.base import Retriever
from lawbot.rag.fake import FakeRetriever

logger = logging.getLogger(__name__)


def _timed_stage(stage):
    def decorate(fn):
        @wraps(fn)
        def measured(state, *args, **kwargs):
            started = time.monotonic()
            try:
                return fn(state, *args, **kwargs)
            finally:
                logging.getLogger("lawbot.timing").info(
                    "agent_timing request_id=%s stage=%s elapsed_ms=%.2f",
                    state.get("request_id") or "-", stage,
                    (time.monotonic() - started) * 1000,
                )
        return measured
    return decorate


def _aux_complete(**kwargs):
    return complete_text(**kwargs, timeout=get_llm_aux_timeout_seconds(), max_tokens=256)


GUARDRAIL_KEYWORDS = ("如何制造炸弹", "洗钱方法", "伪造证件")
DEFAULT_RETRIEVE_TOP_K = 5
MOCK_CHUNK_SIZE = 16
MOCK_CHUNK_SLEEP_S = 0.015

Intent = Literal[
    "chitchat",
    "career_advice",
    "interview_qa",
    "tech_howto",
    "resume_analysis",
    "job_match",
    "job_market",
    "ambiguous",
    "out_of_scope",
]
CaseType = Literal["backend", "frontend", "ml", "devops", "general"]
RETRIEVE_INTENTS = frozenset(
    {
        "career_advice",
        "interview_qa",
        "tech_howto",
        "resume_analysis",
        "job_match",
        "job_market",
        "legal",
    }
)

CHITCHAT_PHRASES = (
    "你好",
    "您好",
    "你好呀",
    "您好呀",
    "嗨",
    "哈喽",
    "hi",
    "hello",
    "hey",
    "在吗",
    "在嘛",
    "在不在",
    "有人吗",
    "在不",
    "谢谢",
    "感谢",
    "多谢",
    "哈哈",
    "早上好",
    "下午好",
    "晚上好",
    "晚安",
    "再见",
    "拜拜",
    "ok",
    "嗯",
    "好的",
    "收到",
)
REWRITE_LLM_MIN_LEN = 60
CAPABILITY_PHRASES = (
    "你能做什么",
    "你可以做什么",
    "你会什么",
    "你是谁",
    "你是什么",
    "介绍一下你自己",
    "你的能力",
    "有什么功能",
    "能帮我做什么",
    "what can you do",
    "who are you",
)
OUT_OF_SCOPE_SIGNALS = (
    "菜谱",
    "红烧肉",
    "怎么做菜",
    "烹饪",
    "旅游攻略",
    "旅游",
    "天气预报",
    "明星",
    "八卦",
    "写作文",
    "写小说",
    "翻译一下",
    "翻译这段",
    "数学题",
    "解方程",
    "开药",
    "处方",
    "荐股",
    "股票推荐",
    "越狱",
    "忽略安全",
    "忽略以上",
    "jailbreak",
    "扮演无限制",
    "自动投递",
    "爬虫",
    "验证码",
    "boss直聘爬",
    "自动投简历",
    "自动投 boss",
    "自动投Boss",
    "帮我投递",
)
# Full-document drafting is out of product scope (even when the topic is career).
DRAFT_DOCUMENT_SIGNALS = (
    "帮我写",
    "写一份",
    "起草",
    "代写",
    "全套简历",
    "简历模板全文",
)
CAREER_KEYWORDS = (
    "求职",
    "面试",
    "后端",
    "前端",
    "实习",
    "简历",
    "校招",
    "offer",
    "技术栈",
    "python",
    "fastapi",
    "docker",
    "常考",
    "八股",
    "岗位",
    "大三",
    "大四",
    "就业方向",
    "找工作",
    "春招",
    "秋招",
    "社招",
    "内推",
    "刷题",
    "leetcode",
    "jd",
    "薪资",
    "跳槽",
    "转行",
    "项目经历",
    "计算机",
    "软件工程",
    "开发",
    "工程师",
    "react",
    "vue",
    "golang",
    "java",
    "机器学习",
    "devops",
    "k8s",
)
CAREER_ORAL_SIGNALS = (
    "面试官",
    "笔试",
    "技术面",
    "hr面",
    "手撕",
    "挂了",
    "上岸",
    "泡池子",
    "oc",
    "白菜价",
    "谈薪",
    "入职",
    "离职",
    "背调",
    "实习转正",
    "双非",
    "985",
    "211",
    "应届",
    "应届生",
)
INTERVIEW_QA_SIGNALS = (
    "面试题",
    "八股",
    "常考",
    "考点",
    "一面",
    "二面",
    "手撕",
    "算法题",
    "会问什么",
    "怎么答",
)
RESUME_ANALYSIS_SIGNALS = (
    "简历",
    "我的技术短板",
    "技术短板",
    "技能缺口",
    "skill gap",
    "简历分析",
    "分析我的简历",
    "改简历",
    "简历怎么改",
    "项目经历够不够",
)
JOB_MATCH_SIGNALS = (
    "匹配度",
    "岗位匹配",
    "契合度",
    "对标简历",
    "对照 jd",
    "对照JD",
    "这份 jd",
    "这份JD",
    "jd 匹配",
    "JD匹配",
    "帮我看看这个岗位",
    "这个岗位适合我吗",
    "岗位要求匹配",
)
JOB_MARKET_SIGNALS = (
    "市场需求",
    "岗位行情",
    "这类岗位要什么技能",
    "方向热门技能",
    "市场要什么",
)
INTERVIEW_FOLLOWUP_SIGNALS = (
    "刚讲完",
    "追问",
    "接下来会问",
    "面试官还会问",
    "深挖",
    "跟进问题",
)
TECH_HOWTO_SIGNALS = (
    "怎么实现",
    "如何实现",
    "怎么用",
    "如何用",
    "原理",
    "区别",
    "部署",
    "配置",
    "报错",
    "bug",
    "debug",
    "docker",
    "fastapi",
    "redis",
    "mysql",
    "微服务",
    "api",
    "写代码",
    "编程",
)
AMBIGUOUS_ONLY = frozenset(
    {
        "怎么办",
        "问一下",
        "想问点事",
        "有事吗",
        "在吗呀",
        "你好吗",
        "帮帮我",
        "请问",
        "咨询一下",
        "有个问题",
    }
)
SHORT_QUERY_MAX_LEN = 12
INTENT_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
VALID_INTENTS = frozenset(
    {
        "chitchat",
        "career_advice",
        "interview_qa",
        "tech_howto",
        "resume_analysis",
        "job_match",
        "job_market",
        "ambiguous",
        "out_of_scope",
    }
)
VALID_CASE_TYPES = frozenset({"backend", "frontend", "ml", "devops", "general"})
_LEGACY_INTENT_ALIASES = {"legal": "career_advice"}
_LEGACY_CASE_TYPE_ALIASES = {
    "labor": "general",
    "contract": "general",
    "tort": "general",
    "family": "general",
}


class AgentState(TypedDict, total=False):
    query: str
    request_id: str
    intent: str
    case_type: str
    topic_shift: bool
    case_type_source: str  # llm | fallback | llm+guard | rule
    collected: str
    search_query: str
    user_issue_plain: str
    citations: list[dict[str, Any]]
    law_hits: list[dict[str, Any]]
    answer: str
    blocked: bool
    block_reason: str
    used_mock: bool
    history: list[dict[str, str]]
    dialogue: str
    missing_facts: list[str]
    confirmed_facts: list[str]
    memory_summary: str
    # Structured short-term slots (checkpointed with the thread).
    task_goal: str
    hard_constraints: list[str]
    open_questions: list[str]
    key_entities: list[str]
    store_facts: list[dict[str, Any]]  # cross-session MemoryStore top-K (not RAG cites)
    active_resume: dict[str, Any]  # parsed resume slots from API (not RAG)
    active_jd: dict[str, Any]  # parsed / pasted JD (not RAG)
    resume_analysis: dict[str, Any]
    skill_gap: dict[str, Any]
    job_match: dict[str, Any]
    interview_followups: list[str]
    facts_sufficient: bool
    followup_rounds: int
    max_followups: int
    min_retrieve_score: float
    retrieval_usable: bool
    phase: str
    fixed_text: str
    stream_system: str
    stream_prompt: str
    mock_text: str
    tool_trace: list[dict[str, Any]]
    self_check_passed: bool
    self_check_issues: list[str]
    self_check_action: str
    conversation_id: str
    province: str
    intent_source: str  # rule | llm | fallback
    facts_source: str  # keyword | llm
    rewrite_source: str  # heuristic | llm | passthrough
    user_id: str


def _normalize_query(query: str) -> str:
    return (query or "").strip()


def _has_career_signal(query: str) -> bool:
    q = query.lower()
    return any(k.lower() in q for k in CAREER_KEYWORDS) or any(
        k in query for k in CAREER_ORAL_SIGNALS
    )


def _wants_interview_followup(query: str) -> bool:
    q = query or ""
    return any(s.lower() in q.lower() or s in q for s in INTERVIEW_FOLLOWUP_SIGNALS)


def _looks_like_jd_paste(query: str) -> bool:
    q = query or ""
    if len(q) >= 80 and any(k in q for k in ("岗位职责", "任职要求", "职位描述", "岗位要求", "JD")):
        return True
    if len(q) >= 120 and ("要求" in q and ("负责" in q or "优先" in q)):
        return True
    return False


def _career_intent_subtype(query: str) -> Intent:
    q = query.lower()
    if any(s.lower() in q or s in query for s in JOB_MATCH_SIGNALS) or _looks_like_jd_paste(query):
        return "job_match"
    if any(s.lower() in q or s in query for s in JOB_MARKET_SIGNALS):
        return "job_market"
    if any(s.lower() in q or s in query for s in RESUME_ANALYSIS_SIGNALS):
        return "resume_analysis"
    if any(s.lower() in q or s in query for s in INTERVIEW_QA_SIGNALS) or _wants_interview_followup(
        query
    ):
        return "interview_qa"
    if any(s.lower() in q or s in query for s in TECH_HOWTO_SIGNALS):
        return "tech_howto"
    return "career_advice"


def _is_draft_document_request(query: str) -> bool:
    q = query or ""
    return any(s in q for s in DRAFT_DOCUMENT_SIGNALS)


def _rule_intent(query: str) -> Intent | None:
    q = _normalize_query(query)
    if not q:
        return "ambiguous"

    q_lower = q.lower()
    compact = re.sub(r"[\s\,\.\!\?，。！？、~～…·]+", "", q_lower)
    has_career = _has_career_signal(q)

    # Pure punctuation / emoji-like noise → clarify, not career pipeline.
    if not compact and not has_career:
        return "ambiguous"
    if compact and not has_career and len(compact) <= 2 and not any(ch.isalnum() for ch in compact):
        return "chitchat"

    if any(p.lower() in q_lower or p.lower() in compact for p in CAPABILITY_PHRASES):
        return "chitchat"

    # Full-document drafting → OOS even when topic words look in-scope.
    if _is_draft_document_request(q):
        return "out_of_scope"

    if not has_career and len(q) <= SHORT_QUERY_MAX_LEN:
        phrases = {p.lower() for p in CHITCHAT_PHRASES}
        if compact in phrases:
            return "chitchat"
        if any(compact == p or compact.startswith(p) for p in phrases):
            if len(compact) <= SHORT_QUERY_MAX_LEN:
                return "chitchat"

    has_oos = any(s.lower() in q_lower for s in OUT_OF_SCOPE_SIGNALS)
    if has_oos and not has_career:
        return "out_of_scope"
    # Scraping / auto-apply: OOS even when mixed with career terms (align OUT_OF_SCOPE_SIGNALS).
    _force_oos_even_with_career = (
        "自动投递",
        "爬虫",
        "验证码",
        "boss直聘爬",
        "自动投简历",
        "自动投 boss",
        "自动投Boss",
        "帮我投递",
    )
    if has_oos and any(s.lower() in q_lower for s in _force_oos_even_with_career):
        return "out_of_scope"

    if has_career:
        return _career_intent_subtype(q)

    if compact in AMBIGUOUS_ONLY or q in AMBIGUOUS_ONLY:
        return "ambiguous"
    return None


def _fallback_intent(query: str) -> Intent:
    q = _normalize_query(query)
    if not q:
        return "ambiguous"
    compact = re.sub(r"[\s\,\.\!\?，。！？、~～]+", "", q.lower())
    if compact in AMBIGUOUS_ONLY or q in AMBIGUOUS_ONLY:
        return "ambiguous"
    if len(q) <= 4 and not _has_career_signal(q):
        return "ambiguous"
    return _career_intent_subtype(q)


def _parse_intent_json(text: str) -> Intent | None:
    if not text:
        return None
    match = INTENT_JSON_RE.search(text)
    raw = match.group(0) if match else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    intent = str(data.get("intent") or "").strip().lower()
    intent = _LEGACY_INTENT_ALIASES.get(intent, intent)
    if intent in VALID_INTENTS:
        return intent  # type: ignore[return-value]
    return None


@_timed_stage("intent")
def classify_intent(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    t0 = time.monotonic()
    query = _normalize_query(state.get("query") or "")
    ruled = _rule_intent(query)
    if ruled is not None:
        source = "rule"
        intent: Intent = ruled
    elif credentials is not None:
        intent = _fallback_intent(query)
        source = "fallback"
        try:
            raw = _aux_complete(
                prompt=build_intent_classify_user_prompt(query=query),
                credentials=credentials,
                system=INTENT_CLASSIFY_SYSTEM_PROMPT,
            )
            parsed = _parse_intent_json(raw)
            if parsed is not None:
                intent = parsed
                source = "llm"
        except Exception:
            logger.exception("intent LLM classify failed; using fallback rules")
    else:
        intent = _fallback_intent(query)
        source = "fallback"

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("agent_timing intent_ms=%s source=%s intent=%s", elapsed_ms, source, intent)
    out = {**state, "intent": intent, "intent_source": source}
    trace_step(
        "classify_intent",
        input_summary=privacy_summary(query),
        output_summary=f"intent={intent} source={source} ms={elapsed_ms}",
    )
    return out


def _history_snippet(history: list[dict[str, str]] | None, *, limit: int = 4) -> str:
    rows = list(history or [])[-limit:]
    if not rows:
        return ""
    lines: list[str] = []
    for item in rows:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content[:120]}")
    return "\n".join(lines)


# Strong signals for fallback + post-LLM guard.
_BACKEND_KEYS = (
    "后端",
    "服务端",
    "fastapi",
    "django",
    "flask",
    "golang",
    "go语言",
    "java",
    "spring",
    "mysql",
    "redis",
    "微服务",
    "api",
)
_FRONTEND_KEYS = (
    "前端",
    "react",
    "vue",
    "javascript",
    "typescript",
    "css",
    "html",
    "webpack",
    "小程序",
)
_ML_KEYS = ("机器学习", "深度学习", "pytorch", "tensorflow", "nlp", "cv", "算法岗")
_DEVOPS_KEYS = ("devops", "docker", "kubernetes", "k8s", "ci/cd", "jenkins", "运维", "sre")
_CASE_TYPE_CONFIDENCE_FLOOR = 0.45


def _case_type_signal_flags(query: str) -> tuple[bool, bool, bool, bool]:
    q = (query or "").lower()
    return (
        any(k.lower() in q for k in _BACKEND_KEYS),
        any(k.lower() in q for k in _FRONTEND_KEYS),
        any(k.lower() in q for k in _ML_KEYS),
        any(k.lower() in q for k in _DEVOPS_KEYS),
    )


def _fallback_case_type(query: str) -> CaseType:
    backendish, frontendish, mlish, devopsish = _case_type_signal_flags(query)
    if backendish and not frontendish:
        return "backend"
    if frontendish and not backendish:
        return "frontend"
    if mlish:
        return "ml"
    if devopsish:
        return "devops"
    return "general"


def _rule_case_type(query: str) -> CaseType | None:
    """Exclusive strong signal → skip case_type LLM. Conflicts / weak → None."""
    backendish, frontendish, mlish, devopsish = _case_type_signal_flags(query)
    active = sum((backendish, frontendish, mlish, devopsish))
    if active != 1:
        return None
    if backendish:
        return "backend"
    if frontendish:
        return "frontend"
    if mlish:
        return "ml"
    if devopsish:
        return "devops"
    return None


def _parse_case_type_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    match = INTENT_JSON_RE.search(text)
    raw = match.group(0) if match else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    case_type = str(data.get("case_type") or "").strip().lower()
    case_type = _LEGACY_CASE_TYPE_ALIASES.get(case_type, case_type)
    if case_type not in VALID_CASE_TYPES:
        return None
    topic_shift = bool(data.get("topic_shift"))
    try:
        confidence = float(data.get("confidence") if data.get("confidence") is not None else 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(data.get("reason") or "").strip()
    return {
        "case_type": case_type,
        "topic_shift": topic_shift,
        "confidence": confidence,
        "reason": reason,
    }


def _reconcile_case_type(
    query: str,
    case_type: str,
    *,
    confidence: float | None,
    source: str,
) -> tuple[CaseType, str, bool, str]:
    """Keyword seatbelt after LLM/fallback. Returns (case_type, source, guard_applied, reason)."""
    backendish, frontendish, mlish, devopsish = _case_type_signal_flags(query)
    raw = case_type if case_type in VALID_CASE_TYPES else "general"
    raw = _LEGACY_CASE_TYPE_ALIASES.get(raw, raw)
    resolved: CaseType = raw  # type: ignore[assignment]
    guard = False
    reason = ""

    flags = (
        ("backend", backendish),
        ("frontend", frontendish),
        ("ml", mlish),
        ("devops", devopsish),
    )
    strong = [name for name, on in flags if on]
    if len(strong) == 1 and resolved == "general":
        resolved = strong[0]  # type: ignore[assignment]
        guard = True
        reason = f"strong_{strong[0]}_overrides_general"

    if (
        source == "llm"
        and confidence is not None
        and confidence < _CASE_TYPE_CONFIDENCE_FLOOR
    ):
        fb = _fallback_case_type(query)
        if fb != resolved:
            resolved = fb
            guard = True
            reason = reason or f"low_confidence_prefer_fallback({fb})"

    out_source = source
    if guard and source == "llm":
        out_source = "llm+guard"
    return resolved, out_source, guard, reason


@_timed_stage("classification")
def classify_case_type(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    """Rule-first when strong exclusive signal; else LLM + narrow fallback + guard."""
    t0 = time.monotonic()
    query = _normalize_query(state.get("query") or "")
    prior_case_type = str(state.get("case_type") or "").strip()
    prior_confirmed = list(state.get("confirmed_facts") or [])
    history_snippet = _history_snippet(list(state.get("history") or []))

    parsed: dict[str, Any] | None = None
    source = "fallback"
    confidence: float | None = None
    llm_reason = ""
    raw_llm_case_type = ""
    ruled = _rule_case_type(query)
    if ruled is None and not any(_case_type_signal_flags(query)) and _rule_intent(query) in {
        "interview_qa", "tech_howto", "resume_analysis", "job_match", "job_market", "career_advice"
    }:
        ruled = "general"
    if ruled is not None:
        case_type: CaseType = ruled
        source = "rule"
        confidence = None
    else:
        if credentials is not None:
            try:
                raw = _aux_complete(
                    prompt=build_case_type_classify_user_prompt(
                        query=query,
                        prior_case_type=prior_case_type,
                        prior_confirmed_facts=prior_confirmed,
                        history_snippet=history_snippet,
                    ),
                    credentials=credentials,
                    system=CASE_TYPE_CLASSIFY_SYSTEM_PROMPT,
                )
                parsed = _parse_case_type_json(raw)
                if parsed is not None:
                    source = "llm"
            except Exception:
                logger.exception("case_type LLM classify failed; using narrow fallback")
                parsed = None

        if parsed is None:
            case_type = _fallback_case_type(query)
            source = "fallback"
            confidence = None
        else:
            case_type = parsed["case_type"]  # type: ignore[assignment]
            raw_llm_case_type = str(case_type)
            confidence = float(parsed.get("confidence") or 0.0)
            llm_reason = str(parsed.get("reason") or "")

    case_type, source, guard_applied, guard_reason = _reconcile_case_type(
        query,
        case_type,
        confidence=confidence,
        source=source,
    )
    topic_shift = bool(parsed.get("topic_shift")) if parsed else False
    if prior_case_type and prior_case_type != case_type:
        topic_shift = True
    elif parsed is None and source != "rule":
        topic_shift = bool(prior_case_type and prior_case_type != case_type)
    elif source == "rule":
        topic_shift = bool(prior_case_type and prior_case_type != case_type)
    # Complete new career question (not a short 请补充 reply) → always shift/clear slots.
    if _looks_standalone_legal_query(query) and not _is_short_supplement(query):
        if prior_case_type or prior_confirmed:
            topic_shift = True

    out = {
        **state,
        "case_type": case_type,
        "topic_shift": topic_shift,
        "case_type_source": source,
    }
    reason = guard_reason or llm_reason or "-"
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "agent_timing case_type_ms=%s source=%s case_type=%s",
        elapsed_ms,
        source,
        case_type,
    )
    trace_step(
        "classify",
        input_summary=privacy_summary(query),
        output_summary=(
            f"case_type={case_type} raw_llm_case_type={raw_llm_case_type or '-'} "
            f"guard_applied={guard_applied} source={source} topic_shift={topic_shift} "
            f"reason={reason} prior={prior_case_type or '-'} ms={elapsed_ms}"
        ),
    )
    return out


# Backward-compatible alias for imports/tests that still call classify(...)
def classify(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    return classify_case_type(state, credentials=credentials)


_SLOT_RULES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "backend": [
        ("意向方向", ("后端", "服务端", "java", "golang", "go", "python", "fastapi")),
        ("技术栈", ("mysql", "redis", "docker", "spring", "django", "flask", "微服务")),
    ],
    "frontend": [
        ("意向方向", ("前端", "react", "vue", "小程序", "h5")),
        ("技术栈", ("javascript", "typescript", "css", "html", "webpack")),
    ],
    "ml": [
        ("意向方向", ("机器学习", "深度学习", "算法岗", "nlp", "cv")),
        ("技术栈", ("pytorch", "tensorflow", "python")),
    ],
    "devops": [
        ("意向方向", ("运维", "devops", "sre", "基础设施")),
        ("技术栈", ("docker", "k8s", "kubernetes", "jenkins", "ci/cd")),
    ],
}

_GENERAL_EVENTS = (
    "求职",
    "面试",
    "实习",
    "校招",
    "简历",
    "后端",
    "前端",
    "python",
    "docker",
    "八股",
    "常考",
    "大三",
    "大四",
    "offer",
    "岗位",
    "就业",
    "转行",
    "项目",
)


def _user_corpus(query: str, history: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    for item in history or []:
        if str(item.get("role")) != "user":
            continue
        text = str(item.get("content") or "").strip()
        if text:
            parts.append(text)
    current = (query or "").strip()
    if current:
        parts.append(current)
    return "\n".join(parts)


def _dialogue(query: str, history: list[dict[str, str]] | None) -> str:
    lines: list[str] = []
    for item in history or []:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        role = "用户" if str(item.get("role")) == "user" else "助手"
        lines.append(f"{role}：{content}")
    current = (query or "").strip()
    if current:
        lines.append(f"用户：{current}")
    return "\n".join(lines)


def _count_followups(history: list[dict[str, str]] | None) -> int:
    count = 0
    for item in history or []:
        if str(item.get("role")) != "assistant":
            continue
        if "请补充：" in str(item.get("content") or ""):
            count += 1
    return count


def _assess_facts(case_type: str, corpus: str) -> tuple[list[str], list[str]]:
    rules = _SLOT_RULES.get(case_type)
    if not rules:
        if any(keyword in corpus for keyword in _GENERAL_EVENTS):
            return [], ["具体事件"]
        return ["具体事件"], []
    missing: list[str] = []
    confirmed: list[str] = []
    corpus_l = corpus.lower()
    for name, keys in rules:
        if any(key.lower() in corpus_l if key.isascii() else key in corpus for key in keys):
            confirmed.append(name)
        else:
            missing.append(name)
    # Career tracks: 意向方向 or 技术栈 alone is enough to retrieve (avoid over-asking).
    if any(n in confirmed for n in ("意向方向", "技术栈")):
        return [], confirmed
    return missing, confirmed


_CAREER_SLOT_NAMES = frozenset({"意向方向", "技术栈"})
_TRACK_SLOT_NAMES = frozenset({"意向方向", "技术栈", "具体诉求"})
_SHORT_SUPPLEMENT_MAX = 40
_STANDALONE_MIN_LEN = 18
_STANDALONE_ASK_KEYS = (
    "是否",
    "怎么办",
    "能不能",
    "可以吗",
    "如何",
    "怎样",
    "该不该",
    "怎么选",
    "？",
    "?",
)
_ATYPICAL_CONTRACT_KEYS = (
    "岗位职责",
    "任职要求",
    "岗位职责",
    "工作经验",
    "工作职责",
)


def _assistant_asked_supplement(history: list[dict[str, str]] | None) -> bool:
    """True when the latest assistant message asked for slot补全."""
    for item in reversed(list(history or [])):
        if str(item.get("role")) != "assistant":
            continue
        return "请补充：" in str(item.get("content") or "")
    return False


def _checkpoint_awaits_supplement(state: AgentState) -> bool:
    """True when prior turn left the thread waiting for a short 请补充 reply.

    chat.py often passes history=None; rely on checkpoint phase / missing slots.
    """
    if str(state.get("phase") or "") == "followup":
        return True
    if list(state.get("missing_facts") or []):
        return True
    if list(state.get("open_questions") or []):
        return True
    return False


_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:万|千)?\s*(?:元|块)")


def _extract_key_entities(query: str, *, prior: list[str] | None = None) -> list[str]:
    """Lightweight rule entities; incremental merge, never LLM-regenerate whole list."""
    q = query or ""
    found: list[str] = []
    for m in _AMOUNT_RE.finditer(q):
        found.append(f"金额:{m.group(0)}")
    for label, keys in (
        ("学校", ("大学", "学院", "大三", "大四", "研一", "研二")),
        ("方向", ("后端", "前端", "算法", "运维", "测试", "产品")),
    ):
        if any(k in q for k in keys):
            found.append(label)
    if "我" in q and "公司" not in found:
        found.append("当事人:我")
    out: list[str] = []
    for name in list(prior or []) + found:
        if name and name not in out:
            out.append(name)
    return out[:12]


def _build_hard_constraints(
    *,
    province: str,
    case_type: str,
    prior: list[str] | None = None,
    topic_reset: bool = False,
) -> list[str]:
    kept: list[str] = []
    if not topic_reset:
        for item in prior or []:
            # Keep durable prefs like province= across topic shift; drop case_type=.
            if str(item).startswith("province="):
                kept.append(str(item))
    if province:
        tag = f"province={province}"
        if tag not in kept:
            kept.append(tag)
    if case_type and case_type != "general":
        tag = f"case_type={case_type}"
        if tag not in kept:
            kept.append(tag)
    return kept


def _is_atypical_contract_query(query: str) -> bool:
    """Long JD / resume paste — skip narrow slot gate."""
    q = query or ""
    return len(q) >= 80 or (any(k in q for k in _ATYPICAL_CONTRACT_KEYS) and len(q) >= 36)


def _looks_standalone_career_query(query: str) -> bool:
    """Complete new question with subject/action/ask — not a short slot reply."""
    q = (query or "").strip()
    if len(q) < _STANDALONE_MIN_LEN:
        return False
    if _is_atypical_contract_query(q):
        return True
    if _has_career_signal(q) and any(k in q for k in _STANDALONE_ASK_KEYS):
        return True
    if any(k in q for k in _STANDALONE_ASK_KEYS):
        return True
    return len(q) >= 40


def _looks_standalone_legal_query(query: str) -> bool:
    return _looks_standalone_career_query(query)


def _is_short_supplement(query: str) -> bool:
    """Short fact patch after 请补充 — must not look like a full new dispute."""
    q = (query or "").strip()
    if not q or len(q) >= _SHORT_SUPPLEMENT_MAX:
        return False
    if _looks_standalone_legal_query(q):
        return False
    if _is_atypical_contract_query(q):
        return False
    return True


def _topic_conflict(prior_confirmed: list[str], query: str, case_type: str) -> bool:
    """Reset slots when the user clearly switches CS track mid-thread."""
    prior = set(prior_confirmed or [])
    if not prior or not (prior & _CAREER_SLOT_NAMES):
        return False
    backendish, frontendish, mlish, devopsish = _case_type_signal_flags(query)
    flags = [backendish, frontendish, mlish, devopsish]
    if sum(flags) != 1:
        return False
    tracks = ("backend", "frontend", "ml", "devops")
    expected = tracks[flags.index(True)]
    return case_type not in {expected, "general"}


def _merge_confirmed(
    case_type: str,
    query: str,
    prior_confirmed: list[str],
    *,
    topic_reset: bool = False,
) -> tuple[list[str], list[str]]:
    """Merge checkpoint confirmed slots with slots found in this turn's query only."""
    if topic_reset or _topic_conflict(prior_confirmed, query, case_type):
        prior_confirmed = []
    _missing_now, confirmed_now = _assess_facts(case_type, query)
    confirmed: list[str] = []
    for name in list(prior_confirmed) + list(confirmed_now):
        if name and name not in confirmed:
            confirmed.append(name)
    # Drop slots that do not belong to the current case_type rule set.
    rules = _SLOT_RULES.get(case_type)
    if rules:
        allowed = {name for name, _keys in rules}
        confirmed = [name for name in confirmed if name in allowed]
    if not rules:
        if confirmed:
            confirmed = [n for n in confirmed if n in _CAREER_SLOT_NAMES] or confirmed_now
            if confirmed:
                return [], confirmed
        return ["具体事件"], []
    slot_names = [name for name, _keys in rules]
    missing = [name for name in slot_names if name not in confirmed]
    return missing, confirmed


_SHORT_QUERY_FACTS_GUARD = 8


def _parse_facts_sufficiency_json(text: str, case_type: str) -> dict[str, Any] | None:
    if not text:
        return None
    match = INTENT_JSON_RE.search(text)
    raw = match.group(0) if match else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "facts_sufficient" not in data:
        return None
    rules = _SLOT_RULES.get(case_type)
    allowed = {name for name, _keys in rules} if rules else {"具体事件"}
    confirmed_raw = data.get("confirmed_facts") or []
    missing_raw = data.get("missing_facts") or []
    if not isinstance(confirmed_raw, list) or not isinstance(missing_raw, list):
        return None
    confirmed: list[str] = []
    for item in confirmed_raw:
        name = str(item or "").strip()
        if name in allowed and name not in confirmed:
            confirmed.append(name)
    missing: list[str] = []
    for item in missing_raw:
        name = str(item or "").strip()
        if name in allowed and name not in missing and name not in confirmed:
            missing.append(name)
    missing = missing[:2]
    sufficient = bool(data.get("facts_sufficient"))
    if sufficient:
        missing = []
        if rules:
            for name, _keys in rules:
                if name not in confirmed:
                    confirmed.append(name)
    else:
        if not missing and rules:
            for name, _keys in rules:
                if name not in confirmed:
                    missing.append(name)
                    break
        sufficient = not missing
    return {
        "facts_sufficient": sufficient,
        "confirmed_facts": confirmed,
        "missing_facts": missing,
        "reason": str(data.get("reason") or "").strip(),
    }


def make_collect(credentials: ProviderCredentials | None = None):
    @_timed_stage("facts")
    def collect(state: AgentState) -> AgentState:
        t0 = time.monotonic()
        query = state.get("query") or ""
        case_type = state.get("case_type") or "general"
        history = list(state.get("history") or [])
        prior_confirmed = list(state.get("confirmed_facts") or [])
        prior_rounds = int(state.get("followup_rounds") or 0)
        prior_entities = list(state.get("key_entities") or [])
        prior_constraints = list(state.get("hard_constraints") or [])
        # Merge only on short 请补充 replies (history and/or checkpoint phase/missing).
        short_sup = _is_short_supplement(query)
        awaiting = _assistant_asked_supplement(history) or _checkpoint_awaits_supplement(state)
        allow_merge = short_sup and awaiting
        topic_reset = (
            bool(state.get("topic_shift"))
            or _topic_conflict(prior_confirmed, query, case_type)
            or (bool(prior_confirmed) and not allow_merge)
        )
        if topic_reset:
            prior_confirmed = []
            prior_rounds = 0
            prior_entities = []
        # Keyword baseline: never mix prior-user corpus into a standalone/new topic turn.
        if allow_merge and not topic_reset:
            missing, confirmed = _merge_confirmed(
                case_type, query, prior_confirmed, topic_reset=False
            )
            prior_rounds = max(prior_rounds, _count_followups(history))
        else:
            missing, confirmed = _assess_facts(case_type, query)
        baseline_missing = list(missing)
        baseline_sufficient = not baseline_missing
        source = "keyword"
        reason = "keyword_slots"

        # Resume / JD match: enough to retrieve/answer.
        intent_now = str(state.get("intent") or "")
        if intent_now == "resume_analysis" or (
            state.get("active_resume")
            and any(s in query for s in ("短板", "简历", "技能缺口", "skill"))
        ):
            missing = []
            if not confirmed:
                confirmed = ["简历技能"]
            baseline_missing = []
            baseline_sufficient = True
            source = "keyword"
            reason = "resume_slots_sufficient"
        if intent_now in {"job_match", "job_market"} or state.get("active_jd") or _looks_like_jd_paste(
            query
        ):
            missing = []
            if not confirmed:
                confirmed = ["岗位JD"]
            baseline_missing = []
            baseline_sufficient = True
            source = "keyword"
            reason = "jd_match_sufficient"

        # Long JD / pasted job text: do not gate on narrow track slots.
        if _is_atypical_contract_query(query):
            missing = []
            if not confirmed:
                confirmed = ["具体诉求"]
            baseline_missing = []
            baseline_sufficient = True
            source = "keyword"
            reason = "atypical_jd_skip_slots"

        # Complete standalone question with any confirmed signal → allow retrieve/answer.
        if (
            not baseline_sufficient
            and _looks_standalone_legal_query(query)
            and (confirmed or _is_atypical_contract_query(query))
        ):
            missing = []
            baseline_missing = []
            baseline_sufficient = True
            reason = "standalone_query_sufficient"

        # Skip facts LLM when keyword baseline already sufficient (cuts TTFT).
        if baseline_sufficient:
            source = source if reason.startswith("atypical") or reason.startswith("standalone") else "keyword"
            if reason == "keyword_slots":
                reason = "baseline_sufficient_skip_llm"
        elif credentials is not None and not (
            len(query.strip()) < _SHORT_QUERY_FACTS_GUARD
            and any(n in baseline_missing for n in _CAREER_SLOT_NAMES)
        ):
            try:
                raw = _aux_complete(
                    prompt=build_facts_sufficiency_user_prompt(
                        query=query,
                        case_type=case_type,
                        prior_confirmed_facts=prior_confirmed if allow_merge else [],
                        history_snippet=_history_snippet(history if allow_merge else []),
                    ),
                    credentials=credentials,
                    system=FACTS_SUFFICIENCY_SYSTEM_PROMPT,
                )
                parsed = _parse_facts_sufficiency_json(raw, case_type)
                if parsed is not None:
                    # Guard: ultra-short query + keyword still missing track slots → keep followup.
                    q_stripped = query.strip()
                    if (
                        parsed["facts_sufficient"]
                        and len(q_stripped) < _SHORT_QUERY_FACTS_GUARD
                        and any(n in baseline_missing for n in _CAREER_SLOT_NAMES)
                    ):
                        reason = "llm_overridden_short_query"
                    else:
                        missing = list(parsed["missing_facts"])
                        confirmed = list(parsed["confirmed_facts"])
                        # Never apply借贷双槽追问 to atypical company queries.
                        if _is_atypical_contract_query(query) and any(
                            n in _TRACK_SLOT_NAMES for n in missing
                        ):
                            missing = []
                            confirmed = list(confirmed) or ["具体事件"]
                            reason = "llm_atypical_contract_override"
                        else:
                            source = "llm"
                            reason = parsed.get("reason") or "llm"
            except Exception:
                logger.exception("facts sufficiency LLM failed; using keyword baseline")

        sufficient = not missing
        province = extract_province(query) or state.get("province") or ""
        summary = f"已确认：{'、'.join(confirmed) or '（无）'}；方向 {case_type}"
        if province:
            summary += f"；地区 {province}"
        collected = f"{summary}\n本轮：{query.strip()}"
        task_goal = (state.get("user_issue_plain") or "").strip() or (query.strip()[:80])
        if topic_reset or not allow_merge:
            task_goal = query.strip()[:80]
        hard_constraints = _build_hard_constraints(
            province=province,
            case_type=str(case_type),
            prior=prior_constraints,
            topic_reset=topic_reset,
        )
        key_entities = _extract_key_entities(
            query, prior=None if topic_reset else prior_entities
        )
        open_questions = list(missing)
        out = {
            **state,
            "collected": collected,
            "dialogue": _dialogue(query, history if history else None),
            "missing_facts": missing,
            "confirmed_facts": confirmed,
            "memory_summary": summary,
            "task_goal": task_goal,
            "hard_constraints": hard_constraints,
            "open_questions": open_questions,
            "key_entities": key_entities,
            "facts_sufficient": sufficient,
            "facts_source": source,
            "followup_rounds": prior_rounds,
            "province": province,
            "topic_shift": topic_reset,
        }
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "agent_timing collect_ms=%s source=%s sufficient=%s",
            elapsed_ms,
            source,
            sufficient,
        )
        trace_step(
            "collect",
            input_summary=privacy_summary(query),
            output_summary=(
                f"case={case_type} topic_reset={topic_reset} sufficient={sufficient} "
                f"source={source} reason={reason} "
                f"missing={','.join(missing) or '无'} confirmed={','.join(confirmed) or '无'} "
                f"ms={elapsed_ms}"
            ),
        )
        return out

    return collect


def collect(state: AgentState) -> AgentState:
    """Keyword-only collect (no LLM). Prefer make_collect(credentials) in the graph."""
    return make_collect(None)(state)


def _heuristic_rewrite(query: str) -> tuple[str, str]:
    q = _normalize_query(query)
    q_lower = q.lower()
    if any(k in q for k in ("面试", "八股", "常考", "手写", "手撕", "一面", "二面")):
        search = f"面试题 {q[:60]}"
        plain = "想了解面试考点或常见问答，准备技术面/笔试。"
        return search, plain
    if any(k in q_lower for k in ("fastapi", "docker", "redis", "mysql", "k8s")) or any(
        k in q for k in ("怎么实现", "如何用", "部署", "报错", "bug", "debug")
    ):
        return f"技术实现 {q[:60]}", f"技术栈/实现类问题：{q[:80]}"
    if any(k in q for k in ("后端", "服务端", "java", "golang", "go", "spring")):
        return f"后端求职 {q[:60]}", "意向后端开发，想了解方向、技能栈或面试准备。"
    if any(k in q_lower for k in ("前端", "react", "vue", "javascript")):
        return f"前端求职 {q[:60]}", "意向前端开发，想了解方向、技能栈或面试准备。"
    if any(k in q for k in ("实习", "校招", "秋招", "春招", "简历", "offer", "求职")):
        return f"求职规划 {q[:60]}", "求职/选岗/简历相关，想了解可行路径与准备重点。"
    if any(k in q for k in ("机器学习", "深度学习", "算法岗", "pytorch")):
        return f"ML求职 {q[:60]}", "意向算法/机器学习方向，想了解技能栈与面试要点。"
    return q, f"用户说：{q[:80]}"


def _heuristic_rewrite_matched(query: str, search: str, plain: str) -> bool:
    """True when heuristic mapped to a concrete case pattern (not passthrough)."""
    q = _normalize_query(query)
    return not (search == q and plain == f"用户说：{q[:80]}")


def _parse_rewrite_json(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    match = INTENT_JSON_RE.search(text)
    raw = match.group(0) if match else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    sq = str(data.get("search_query") or "").strip()
    plain = str(data.get("user_issue_plain") or "").strip()
    if sq or plain:
        return sq or plain, plain or sq
    return None


@_timed_stage("rewrite")
def rewrite_issue(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    # Retrieval rewrite must use this turn's raw query only — never slot summary.
    t0 = time.monotonic()
    query = _normalize_query(state.get("query") or "")
    search, plain = _heuristic_rewrite(query)
    matched = _heuristic_rewrite_matched(query, search, plain)
    source = "heuristic" if matched else "passthrough"
    # LLM only when long + heuristic miss (strict TTFT gate).
    use_llm = (
        credentials is not None
        and len(query) > REWRITE_LLM_MIN_LEN
        and not matched
        and _rule_intent(query) is None
    )
    if use_llm:
        try:
            raw = _aux_complete(
                prompt=build_rewrite_user_prompt(query=query),
                credentials=credentials,
                system=REWRITE_SYSTEM_PROMPT,
            )
            parsed = _parse_rewrite_json(raw)
            if parsed is not None:
                search, plain = parsed
                source = "llm"
        except Exception:
            logger.exception("rewrite_issue LLM failed; using heuristics")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("agent_timing rewrite_ms=%s source=%s", elapsed_ms, source)
    return {
        **state,
        "search_query": search,
        "user_issue_plain": plain,
        "rewrite_source": source,
    }


def _citation_from_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_name": hit.get("law_name") or "",
        "article_no": hit.get("article_no") or "",
        "text": hit.get("text") or "",
        "source_id": hit.get("source_id") or "",
        "effective_date": hit.get("effective_date"),
        "status": hit.get("status"),
        "jurisdiction": hit.get("jurisdiction"),
        "category": hit.get("category"),
        "domain": hit.get("domain"),
    }


_QUERY_TOPIC_KEYS = (
    "后端",
    "前端",
    "python",
    "docker",
    "面试",
    "实习",
    "校招",
    "简历",
    "八股",
    "redis",
    "mysql",
    "fastapi",
    "react",
    "vue",
    "java",
    "golang",
    "算法",
    "机器学习",
    "devops",
    "k8s",
    "全栈",
    "测试",
    "安全",
    "数据工程",
    "数据库",
    "运维",
    "网络",
    "移动端",
    "安卓",
    "ios",
)


def _query_topic_keys(*texts: str) -> list[str]:
    blob = " ".join(t for t in texts if t).lower()
    return [k for k in _QUERY_TOPIC_KEYS if k.lower() in blob]


def _is_role_requirements_query(query: str) -> bool:
    text = (query or "").lower()
    return any(key in text for key in ("技术栈", "技能要求", "岗位要求", "任职要求", "需要掌握", "应当具备", "需要具备"))


def _is_role_research_query(query: str) -> bool:
    text = (query or "").lower()
    return any(key in text for key in ("岗位", "职位", "工程师", "全栈", "后端", "前端", "开发", "运维", "架构师"))


def _hit_matches_query_topic(hit: dict[str, Any], query: str, *, q_keys: list[str] | None = None) -> bool:
    """Loose topic overlap: drop weak hits that share no query topic keywords."""
    keys = q_keys if q_keys is not None else _query_topic_keys(query or "")
    if not keys:
        return True
    blob = (
        f"{hit.get('law_name') or ''} {hit.get('text') or ''} "
        f"{hit.get('article') or ''} {hit.get('article_no') or ''} "
        f"{hit.get('domain') or ''}"
    ).lower()
    return any((k.lower() in blob if k.isascii() else k in blob) for k in keys)


def _kb_domains_for_intent(intent: str, *, followup: bool = False) -> list[str]:
    intent = (intent or "career_advice").strip().lower()
    intent = _LEGACY_INTENT_ALIASES.get(intent, intent)
    if followup:
        return ["gotchas", "interview_qa"]
    if intent == "tech_howto":
        return ["tech_docs", "interview_qa"]
    if intent == "resume_analysis":
        return ["tech_docs", "interview_qa", "job_skills"]
    if intent in {"job_match", "job_market"}:
        return ["job_skills", "interview_qa"]
    if intent == "career_advice":
        return ["job_skills", "interview_qa"]
    if intent == "interview_qa":
        return ["interview_qa"]
    return ["interview_qa"]


def make_retrieve(retriever: Retriever, top_k: int = DEFAULT_RETRIEVE_TOP_K):
    @_timed_stage("retrieval")
    def retrieve(state: AgentState) -> AgentState:
        t0 = time.monotonic()
        # Prefer rewritten search_query / raw query — never collected slot summary.
        search_q = (state.get("search_query") or "").strip()
        raw_q = (state.get("query") or "").strip()
        query = search_q or raw_q
        q_keys = _query_topic_keys(search_q, raw_q)
        intent = str(state.get("intent") or "career_advice")
        followup = _wants_interview_followup(raw_q) or _wants_interview_followup(query)
        role_requirements = _is_role_requirements_query(raw_q)
        domains = ["job_skills"] if role_requirements else _kb_domains_for_intent(intent, followup=followup)
        if intent == "interview_qa" and not followup and _is_role_research_query(raw_q):
            domains = ["job_skills"] if role_requirements else ["interview_qa", "job_skills"]
        if role_requirements and q_keys:
            q_keys = [key for key in q_keys if key not in {"面试", "实习", "校招", "简历", "八股"}]
        if role_requirements:
            # Keep the full role phrase so title/alias matches distinguish, for
            # example, software testing from penetration testing.
            query = raw_q or query
        ctx = ToolContext(
            retriever=retriever,
            tool_trace=list(state.get("tool_trace") or []),
            active_resume=state.get("active_resume"),
            active_jd=state.get("active_jd"),
        )
        resume_analysis: dict[str, Any] = dict(state.get("resume_analysis") or {})
        skill_gap: dict[str, Any] = dict(state.get("skill_gap") or {})
        job_match: dict[str, Any] = dict(state.get("job_match") or {})
        interview_followups: list[str] = list(state.get("interview_followups") or [])
        if intent == "resume_analysis" or state.get("active_resume"):
            ar = execute_tool("analyze_resume", {"focus": "skills"}, ctx)
            if ar.ok and isinstance(ar.output, dict):
                resume_analysis = ar.output
            sg = execute_tool(
                "skill_gap_plan",
                {"target_role": "", "top_k": min(5, top_k)},
                ctx,
            )
            if sg.ok and isinstance(sg.output, dict):
                skill_gap = sg.output
        if intent in {"job_match", "job_market"} or state.get("active_jd"):
            jd_text = ""
            active_jd = state.get("active_jd") or {}
            jd_text = str(active_jd.get("raw_text") or active_jd.get("text") or "")
            if not jd_text and _looks_like_jd_paste(raw_q):
                jd_text = raw_q
            mj = execute_tool(
                "match_job",
                {
                    "jd_text": jd_text,
                    "target_role": "",
                    "top_k": min(5, top_k),
                },
                ctx,
            )
            if mj.ok and isinstance(mj.output, dict):
                job_match = mj.output
            if intent == "job_market" and not skill_gap:
                sg = execute_tool(
                    "skill_gap_plan",
                    {"target_role": str(job_match.get("target_role") or ""), "top_k": min(5, top_k)},
                    ctx,
                )
                if sg.ok and isinstance(sg.output, dict):
                    skill_gap = sg.output
        if followup:
            fu = execute_tool(
                "interview_followup",
                {"topic": query or raw_q, "top_k": 3},
                ctx,
            )
            if fu.ok and isinstance(fu.output, dict):
                interview_followups = list(fu.output.get("directions") or [])
                extra_hits = list(fu.output.get("kb_hits") or [])
            else:
                extra_hits = []
        else:
            extra_hits = []
        outcome = execute_tool(
            "search_kb",
            {"query": query, "top_k": top_k, "domains": domains},
            ctx,
        )
        hits = list(outcome.output or []) if outcome.ok else []
        if extra_hits:
            seen = {str(h.get("source_id") or "") for h in hits}
            for h in extra_hits:
                sid = str(h.get("source_id") or "")
                if sid and sid not in seen:
                    hits.append(h)
                    seen.add(sid)
        # Merge skill_gap / job_match kb hits
        for extra_list in (
            skill_gap.get("kb_hits") if intent in {"resume_analysis", "job_market"} else None,
            job_match.get("citations") if intent in {"job_match", "job_market"} else None,
        ):
            if not extra_list:
                continue
            seen = {str(h.get("source_id") or "") for h in hits}
            for h in extra_list:
                sid = str(h.get("source_id") or "")
                if sid and sid not in seen:
                    hits.append(h)
                    seen.add(sid)
        raw_threshold = state.get("min_retrieve_score")
        threshold = 0.6 if raw_threshold is None else float(raw_threshold)
        # Resume / followup / job_match paths can answer from slots even with weaker retrieval.
        if intent == "resume_analysis" and resume_analysis.get("has_resume"):
            threshold = min(threshold, 0.35)
        if intent in {"job_match", "job_market"} and job_match:
            threshold = min(threshold, 0.35)
        if followup and interview_followups:
            threshold = min(threshold, 0.35)
        top_score = max((float(hit.get("score") or 0.0) for hit in hits), default=0.0)
        usable = bool(hits) and top_score >= threshold
        if intent == "resume_analysis" and resume_analysis.get("has_resume"):
            usable = True
        if intent in {"job_match", "job_market"} and job_match:
            usable = True
        if followup and interview_followups:
            usable = True
        if usable and hits:
            high_bar = max(threshold + 0.15, 0.75)
            filtered: list[dict[str, Any]] = []
            for hit in hits:
                score = float(hit.get("score") or 0.0)
                topic_ok = _hit_matches_query_topic(hit, query, q_keys=q_keys)
                # No domain free-pass: need keyword overlap or high retrieval score.
                if q_keys:
                    if topic_ok and (role_requirements or score >= threshold):
                        filtered.append(hit)
                elif score >= high_bar or topic_ok:
                    filtered.append(hit)
            hits = filtered if role_requirements else (filtered or hits)
            top_score = max((float(hit.get("score") or 0.0) for hit in hits), default=0.0)
            usable = bool(hits) and top_score >= threshold
            if intent == "resume_analysis" and resume_analysis.get("has_resume"):
                usable = True
            if intent in {"job_match", "job_market"} and job_match:
                usable = True
            if followup and interview_followups:
                usable = True
        citations = [_citation_from_hit(hit) for hit in hits] if (usable and hits) else []
        source_ids = [str(hit.get("source_id") or "") for hit in hits if hit.get("source_id")]
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "agent_timing retrieve_ms=%s hits=%s usable=%s",
            elapsed_ms,
            len(hits),
            usable,
        )
        trace_step(
            "search_kb",
            input_summary=privacy_summary(query),
            output_summary=(
                f"domains={','.join(domains)} hits={len(hits)} usable={usable} "
                f"top={top_score:.3f} ms={elapsed_ms}"
            ),
            source_ids=source_ids,
        )
        return {
            **state,
            "citations": citations,
            "resume_analysis": resume_analysis,
            "skill_gap": skill_gap,
            "job_match": job_match,
            "interview_followups": interview_followups,
            "law_hits": hits,
            "retrieval_usable": usable,
            "tool_trace": ctx.tool_trace,
        }

    return retrieve


def _missing_label(state: AgentState) -> str:
    missing = state.get("missing_facts") or ["关键事实"]
    return "、".join(missing)


@_timed_stage("prepare_answer")
def prepare_followup(state: AgentState) -> AgentState:
    query = state.get("query") or ""
    case_type = state.get("case_type") or "general"
    dialogue = state.get("dialogue") or _dialogue(query, state.get("history"))
    missing = [item.strip() for item in (state.get("missing_facts") or []) if str(item).strip()]
    if _is_atypical_contract_query(query) or case_type == "general":
        missing = ["关键信息"]
        names = "关键信息"
        question = (
            "请补充：用一两句说明你的专业/意向方向或具体问题。"
            "先说最关键的一项即可，补全前不做检索，也不下结论。"
        )
    else:
        if not missing:
            missing = ["关键事实"]
        names = "、".join(missing)
        question = f"请补充：{names}。先说最关键的一项即可，补全前不做检索，也不下结论。"
    ctx = ToolContext(tool_trace=list(state.get("tool_trace") or []))
    outcome = execute_tool(
        "ask_clarification",
        {"missing_facts": missing, "question": question},
        ctx,
    )
    text = str(outcome.output or "") if outcome.ok else ""
    rounds = int(state.get("followup_rounds") or 0) + 1
    trace_step(
        "ask_clarification",
        input_summary=f"missing={','.join(missing)}",
        output_summary=redact_text(text),
        action="clarify",
    )
    return {
        **state,
        "phase": "followup" if outcome.ok else "report_failed",
        "citations": [],
        "dialogue": dialogue,
        "fixed_text": text,
        "mock_text": text or _soft_fail_answer(query=state.get("query") or "", has_citations=False),
        "stream_system": FOLLOWUP_SYSTEM_PROMPT,
        "stream_prompt": build_followup_user_prompt(dialogue=dialogue, missing=names),
        "retrieval_usable": False,
        "tool_trace": ctx.tool_trace,
        "used_mock": True,
        "followup_rounds": rounds,
    }


@_timed_stage("prepare_answer")
def prepare_staged(state: AgentState) -> AgentState:
    names = _missing_label(state)
    dialogue = state.get("dialogue") or _dialogue(state.get("query") or "", state.get("history"))
    fixed = f"信息不足，建议补充{names}。在补充这些事实前，无法给出确定结论。"
    trace_step(
        "staged",
        input_summary=f"missing={names}",
        output_summary=redact_text(fixed),
        action="insufficient",
    )
    return {
        **state,
        "phase": "staged",
        "citations": [],
        "dialogue": dialogue,
        "fixed_text": fixed,
        "mock_text": fixed,
        "stream_system": STAGED_SYSTEM_PROMPT,
        "stream_prompt": build_staged_user_prompt(dialogue=dialogue, missing=names),
        "retrieval_usable": False,
    }


def _heuristic_no_basis_advice(query: str, case_type: str) -> str:
    q = query or ""
    ct = (case_type or "general").lower()
    if ct == "backend" or "后端" in q:
        return "可先补齐 Python/数据库/基础框架能力，做 1～2 个可讲清的后端项目，再针对目标厂笔试与八股系统复习。"
    if ct == "frontend" or "前端" in q:
        return "夯实 HTML/CSS/JS 与主流框架，准备作品或实习项目，按岗位 JD 列出技能差距逐项补。"
    if ct == "ml" or any(k in q for k in ("机器学习", "算法岗")):
        return "明确基础课与论文/竞赛/项目亮点，刷题与手撕并重，投递时区分研究岗与工程岗要求。"
    if ct == "devops" or "运维" in q.lower():
        return "从 Linux、网络、Docker/K8s 与 CI 流水线入手，结合实验环境积累可演示的运维案例。"
    if any(k in q for k in ("面试", "八股", "笔试")):
        return "把问题拆成考点+项目延伸，先对照知识库常考题自测，再对照简历准备可量化案例。"
    return "可先明确意向岗位与技术栈，对照 JD 列差距；简历与项目各准备一条能讲清细节的故事，再按校招/社招节奏投递。"


def _heuristic_report_args(state: AgentState, *, hit: bool) -> dict[str, str]:
    issue = (state.get("user_issue_plain") or state.get("query") or "你的问题")[:80]
    query = state.get("query") or ""
    case_type = state.get("case_type") or "general"
    if not hit:
        return {
            "direction": "当前知识库未命中可直接对照的条目，以下为通用求职/学习路径提示。",
            "key_points": f"就「{issue}」，可先按目标岗位拆解技能树与常见面试考点，再对照简历查漏补缺。",
            "advice": _heuristic_no_basis_advice(query, case_type),
            "risk": "勿编造经历或证书；勿使用爬虫、自动投递等违规手段。",
        }
    lines = [format_basis_line(citation) for citation in (state.get("citations") or [])[:3]]
    basis = "\n".join(lines) if lines else "检索到知识库片段，请对照引用卡片。"
    return {
        "direction": basis,
        "key_points": f"结合「{issue}」，回答须与目标岗位/技术栈一致，并突出可验证的项目细节。",
        "advice": "按检索要点列学习顺序与练题重点，简历中用数据说明贡献。",
        "risk": "招聘要求因公司而异；涉及合规与隐私的方案请人工复核。",
    }


def _parse_report_args(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    raw = match.group(0) if match else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _model_report_args(
    state: AgentState,
    credentials: ProviderCredentials,
    *,
    doubtful: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    cites = state.get("law_hits") or state.get("citations") or []
    cite_note = format_citation_block(list(cites) if cites else [])
    prompt = (
        "只输出 JSON，键为 direction、key_points、advice、risk，值都是非空字符串。\n"
        "direction/key_points 只能使用下面检索结果中的标题与片段，禁止编造出处，"
        "禁止输出内部知识库编号。\n"
        f"问题：{state.get('query') or ''}\n"
        f"检索结果：\n{cite_note}\n"
    )
    if doubtful:
        banned = "、".join(f"《{law}》{article}" for law, article in doubtful)
        prompt += f"以下引用存疑，不要再写：{banned}。\n"
    if not cites:
        prompt += "未检索到明确条目时，direction 须写明未命中知识库，禁止假装有资料依据。\n"
    raw = complete_text(
        prompt=prompt,
        credentials=credentials,
        system="你只输出一个 JSON 对象，键只能是 direction、key_points、advice、risk。",
    )
    return _parse_report_args(raw)


@_timed_stage("prepare_answer")
def prepare_legal_report(
    state: AgentState,
    *,
    credentials: ProviderCredentials | None,
    hit: bool,
) -> AgentState:
    dialogue = state.get("dialogue") or _dialogue(state.get("query") or "", state.get("history"))
    law_hits = list(state.get("law_hits") or [])
    use_hits = hit and not needs_unverified_fallback(state.get("query") or "", law_hits)
    report_state: AgentState = state if use_hits else {**state, "citations": []}
    citations = list(report_state.get("citations") or []) if use_hits else []
    ctx = ToolContext(tool_trace=list(state.get("tool_trace") or []))
    user_query = (state.get("query") or "").strip()
    # Prompt context may include collected; soft-fail display must use raw user_query only.
    query = state.get("collected") or user_query

    def _render(args: dict[str, Any]) -> tuple[bool, str]:
        outcome = execute_tool("emit_career_report", args, ctx)
        if not outcome.ok:
            return False, ""
        return True, str(outcome.output or "")

    def _apply_province(text: str) -> str:
        if state.get("province") and LOCAL_LAW_NOTE not in text:
            if "## 风险提示" in text:
                return text.replace(
                    "## 风险提示",
                    f"## 风险提示\n\n{LOCAL_LAW_NOTE}",
                    1,
                )
            return f"{text.rstrip()}\n\n{LOCAL_LAW_NOTE}"
        return text

    def _slot_prompt_kwargs() -> dict[str, Any]:
        return {
            "task_goal": str(state.get("task_goal") or ""),
            "hard_constraints": list(state.get("hard_constraints") or []),
            "open_questions": list(state.get("open_questions") or []),
            "key_entities": list(state.get("key_entities") or []),
            "confirmed_facts": list(state.get("confirmed_facts") or []),
            "memory_summary": str(state.get("memory_summary") or ""),
            "history": list(state.get("history") or []),
            "store_facts": list(state.get("store_facts") or []),
            "active_resume": state.get("active_resume"),
            "active_jd": state.get("active_jd"),
            "resume_analysis": state.get("resume_analysis"),
            "skill_gap": state.get("skill_gap"),
            "job_match": state.get("job_match"),
            "interview_followups": list(state.get("interview_followups") or []),
        }

    # Stream path: credentials + usable hits → defer body to complete_text_stream.
    if credentials is not None and use_hits and citations:
        prompt = build_answer_user_prompt(
            query=query,
            case_type=state.get("case_type") or "general",
            citations=citations,
            user_issue_plain=state.get("user_issue_plain"),
            search_query=state.get("search_query"),
            **_slot_prompt_kwargs(),
        )
        trace_step(
            "emit_career_report",
            input_summary=f"hit={use_hits} cites={len(citations)}",
            output_summary="stream_deferred",
            action="stream",
        )
        return {
            **state,
            "phase": "analyze",
            "citations": citations,
            "dialogue": dialogue,
            "fixed_text": "",
            "mock_text": _soft_fail_answer(query=user_query, has_citations=True),
            "stream_system": ANSWER_SYSTEM_PROMPT,
            "stream_prompt": prompt,
            "tool_trace": ctx.tool_trace,
            "used_mock": False,
            "retrieval_usable": True,
        }

    # Empty retrieval + credentials → LLM stream with NO_BASIS prompts (no fake citations).
    if credentials is not None and not use_hits:
        no_basis_prompt = build_no_basis_user_prompt(
            dialogue=dialogue,
            query=query,
            user_issue_plain=state.get("user_issue_plain"),
            case_type=state.get("case_type") or "general",
            **_slot_prompt_kwargs(),
        )
        heuristic_fallback = _render(_heuristic_report_args(report_state, hit=False))
        mock_fallback = (
            heuristic_fallback[1]
            if heuristic_fallback[0]
            else _soft_fail_answer(query=user_query, has_citations=False)
        )
        trace_step(
            "emit_career_report",
            input_summary="hit=False cites=0",
            output_summary="stream_deferred_no_basis",
            action="stream",
        )
        return {
            **state,
            "phase": "no_basis",
            "citations": [],
            "dialogue": dialogue,
            "fixed_text": "",
            "mock_text": mock_fallback,
            "stream_system": NO_BASIS_SYSTEM_PROMPT,
            "stream_prompt": no_basis_prompt,
            "tool_trace": ctx.tool_trace,
            "used_mock": False,
            "retrieval_usable": False,
        }

    # Heuristic path: no credentials only.
    used_mock = True
    ok, text = _render(_heuristic_report_args(report_state, hit=use_hits))
    if not ok:
        fail = _soft_fail_answer(query=user_query, has_citations=False)
        trace_step(
            "emit_career_report",
            input_summary=f"hit={use_hits}",
            output_summary="report_failed",
            action="fail",
        )
        return {
            **state,
            "phase": "report_failed",
            "citations": [],
            "dialogue": dialogue,
            "fixed_text": "",
            "mock_text": fail,
            "tool_trace": ctx.tool_trace,
            "used_mock": True,
            "retrieval_usable": use_hits,
        }

    trace_step(
        "emit_career_report",
        input_summary=f"hit={use_hits} cites={len(citations)}",
        output_summary=redact_text(text),
    )

    def _regenerate(marked: str, doubtful: list[tuple[str, str]], hits: list[dict[str, Any]]) -> str:
        if not use_hits:
            return marked
        draft: AgentState = {**report_state, "citations": list(supported_index(hits).values())}
        rebuilt_ok, rebuilt = _render(_heuristic_report_args(draft, hit=bool(draft["citations"])))
        return rebuilt if rebuilt_ok else marked

    career_hits = any(
        str(h.get("domain") or h.get("category") or "")
        in {"interview_qa", "tech_docs", "gotchas", "job_skills"}
        for h in law_hits
    )
    if career_hits:
        from lawbot.agent.citations import CitationRepair

        repaired = CitationRepair(text=text, citations=list(citations))
    else:
        repaired = repair_citations(text, citations, law_hits, _regenerate)
    # Rule-only self-check in-graph (no second LLM).
    checked = run_self_check(
        repaired.text,
        repaired.citations if use_hits else [],
        law_hits if use_hits else [],
        None,
    )
    final_text = _apply_province(checked.text)
    final_citations = list(checked.citations) if use_hits else []
    # Career KB: keep citations even if soft downgrade (statute self-check is law-oriented).
    if checked.action == "downgrade" and not career_hits:
        final_citations = []
    elif checked.action == "downgrade" and career_hits and use_hits and not final_citations:
        final_citations = list(citations)
    phase = "analyze" if final_citations else "no_basis"
    trace_step(
        "self_check",
        input_summary=f"phase_in={phase}",
        output_summary=redact_text(final_text),
        self_check_issues=list(checked.issues),
        action=checked.action,
    )
    return {
        **state,
        "phase": phase,
        "citations": final_citations,
        "dialogue": dialogue,
        "fixed_text": final_text,
        "mock_text": final_text,
        "stream_system": "",
        "stream_prompt": "",
        "tool_trace": ctx.tool_trace,
        "used_mock": used_mock,
        "retrieval_usable": bool(final_citations),
        "self_check_passed": checked.passed,
        "self_check_issues": list(checked.issues),
        "self_check_action": checked.action,
    }


@_timed_stage("prepare_answer")
def prepare_chitchat(state: AgentState) -> AgentState:
    query = (state.get("query") or "").strip()
    mock = _mock_chitchat(query)
    # Rule/fallback chitchat: local mock only (0 LLM). LLM-classified chitchat may stream.
    use_mock = state.get("intent_source") != "llm"
    if use_mock:
        return {
            **state,
            "collected": query,
            "citations": [],
            "phase": "chitchat",
            "dialogue": state.get("dialogue") or _dialogue(query, state.get("history")),
            "fixed_text": mock,
            "mock_text": mock,
            "stream_system": "",
            "stream_prompt": "",
            "used_mock": True,
        }
    return {
        **state,
        "collected": query,
        "citations": [],
        "phase": "chitchat",
        "dialogue": state.get("dialogue") or _dialogue(query, state.get("history")),
        "fixed_text": "",
        "mock_text": mock,
        "stream_system": CHITCHAT_SYSTEM_PROMPT,
        "stream_prompt": build_chitchat_user_prompt(query=query),
        "used_mock": False,
    }


@_timed_stage("prepare_answer")
def prepare_clarify(state: AgentState) -> AgentState:
    query = (state.get("query") or "").strip()
    return {
        **state,
        "collected": query,
        "citations": [],
        "phase": "clarify",
        "dialogue": state.get("dialogue") or _dialogue(query, state.get("history")),
        "fixed_text": "",
        "mock_text": _mock_clarify(query),
        "stream_system": CLARIFY_SYSTEM_PROMPT,
        "stream_prompt": build_clarify_user_prompt(query=query),
    }


@_timed_stage("prepare_answer")
def prepare_out_of_scope(state: AgentState) -> AgentState:
    query = (state.get("query") or "").strip()
    return {
        **state,
        "collected": query,
        "citations": [],
        "phase": "out_of_scope",
        "dialogue": state.get("dialogue") or _dialogue(query, state.get("history")),
        "fixed_text": "",
        "mock_text": _mock_out_of_scope(query),
        "stream_system": OUT_OF_SCOPE_SYSTEM_PROMPT,
        "stream_prompt": build_out_of_scope_user_prompt(query=query),
    }


def _mock_chitchat(query: str) -> str:
    return (
        "你好！我是 **CareerBot** 计算机求职助手，聚焦**面试备考、技术答疑与选岗规划**。"
        f"你可以直接说专业、意向方向或粘贴面试题/JD；当前收到的是「{query[:20] or '问候'}」。"
    )


def _mock_clarify(query: str) -> str:
    return (
        f"根据你说的「{query[:40] or '……'}」，我理解你可能想咨询，但还不太清楚具体诉求。"
        "能再用一句话说明：**你的背景、意向方向或具体问题**吗？"
        "（例如年级专业、想走后端还是前端、或一道面试题——选一个方便说的即可。）"
    )


def _mock_out_of_scope(query: str) -> str:
    q = query or ""
    if _is_draft_document_request(q):
        return (
            "抱歉，我**不能代写完整简历/作品集全文**。"
            "我是 **CareerBot**，提供求职与面试方面的思路与要点，不提供代写投递材料。"
            "若你想优化某段经历表述，可粘贴片段说明目标岗位。"
        )
    if any(
        s in q
        for s in (
            "自动投递",
            "爬虫",
            "验证码",
            "boss直聘爬",
            "自动投简历",
            "自动投 Boss",
            "自动投boss",
            "帮我投递",
        )
    ):
        return (
            f"{AUTO_DELIVER_REFUSAL}\n\n"
            "**人工投递检查清单：**\n"
            "- 对照 JD 核对简历关键词与项目表述\n"
            "- 通过官方渠道手工投递并记录进度\n"
            "- 可先让我做岗位契合度分析，再由你人工投递\n"
        )
    return (
        f"抱歉，我无法协助「{q[:40] or '该请求'}」这类非求职相关事项。"
        "我是 **CareerBot**，欢迎咨询后端/前端/算法方向、面试题与技术实现问题。"
    )


def _soft_fail_answer(*, query: str, has_citations: bool) -> str:
    """User-facing fallback when LLM stream and non-stream both fail."""
    q = (query or "").strip()[:40] or "你的问题"
    if has_citations:
        hint = "刚才检索到一些知识库条目，但模型未能据此完成作答。"
    else:
        hint = "当前未能生成完整答复。"
    return (
        f"抱歉，{hint}请稍后重试；若持续失败，可新开一个会话再问。\n"
        f"本轮问题：「{q}」。"
    )


def _generation_fail_answer(*, user_query: str, mock_text: str = "") -> str:
    """Prefer prepare-stage topical mock_text; else soft-fail with raw user query only."""
    text = (mock_text or "").strip()
    if text and not text.startswith("抱歉，") and "本轮问题：" not in text[:80]:
        # Avoid re-using a prior soft-fail that may have embedded polluted context.
        if "已确认：" not in text:
            return text
    return _soft_fail_answer(query=user_query, has_citations=False)


def _mock_answer(state: AgentState) -> str:
    intent = str(state.get("intent") or "career_advice")
    intent = _LEGACY_INTENT_ALIASES.get(intent, intent)
    query = state.get("query") or state.get("collected") or ""
    issue = state.get("user_issue_plain") or query

    if intent == "chitchat":
        return _mock_chitchat(query)
    if intent == "ambiguous":
        return _mock_clarify(query)
    if intent == "out_of_scope":
        return _mock_out_of_scope(query)

    cites = state.get("citations") or []

    if not cites:
        return (
            f"当前**未配置可用模型供应商**，且**未检索到知识库命中**，"
            f"无法就「{query[:40]}」生成贴题分析。\n\n"
            f"请在 Admin 启用 LLM 供应商，或导入求职/技术知识库后再试。\n\n"
            f"## 你可以怎么做\n\n"
            f"- {_heuristic_no_basis_advice(query, state.get('case_type') or 'general')}\n"
        )

    ref_items = []
    for c in cites[:3]:
        title = c.get("law_name") or "知识库条目"
        section = c.get("article_no") or ""
        text = (c.get("text") or "")[:80]
        ref_items.append(f"- **{title}** {section}：{text}…")
    refs_md = "\n".join(ref_items)
    return (
        f"## 简单说\n\n"
        f"结合你说的「{query[:40]}」，可先对照检索到的面试/技术要点梳理回答提纲。\n\n"
        f"## 你可以怎么做\n\n"
        f"- 把问题拆成定义、原理、项目实践三层准备；\n"
        f"- 对照 JD 补 1～2 个可量化项目细节；\n"
        f"- 不确定的考点回到知识库条目核对。\n\n"
        f"## 方向或要点\n\n"
        f"{refs_md}\n\n"
        f"> 完整片段见引用卡片。归纳：{issue[:80]}\n\n"
        f"## 注意\n\n"
        f"- 答案因公司与岗位而异，投递前请核对官网要求。\n\n"
        f"## 声明\n\n"
        f"本回复为系统**模拟回复**，不构成官方招聘承诺；请以企业通知与自学规划为准。"
    )


def _iter_mock_chunks(text: str, chunk_size: int = MOCK_CHUNK_SIZE) -> Iterator[str]:
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


def make_answer(credentials: ProviderCredentials | None):
    """Career-path answer node (colloquial template)."""

    def answer(state: AgentState) -> AgentState:
        legal_state = {**state, "intent": state.get("intent") or "career_advice"}
        if credentials is None:
            logger.info("LLM answer using mock stream (no enabled provider)")
            return {
                **state,
                "answer": strip_internal_ids(_mock_answer(legal_state)),
                "used_mock": True,
            }

        user_query = (state.get("query") or "").strip()
        query = state.get("collected") or user_query
        cites = state.get("citations") or []
        prompt = build_answer_user_prompt(
            query=query,
            case_type=state.get("case_type") or "general",
            citations=cites,
            user_issue_plain=state.get("user_issue_plain"),
            search_query=state.get("search_query"),
            task_goal=str(state.get("task_goal") or ""),
            hard_constraints=list(state.get("hard_constraints") or []),
            open_questions=list(state.get("open_questions") or []),
            key_entities=list(state.get("key_entities") or []),
            confirmed_facts=list(state.get("confirmed_facts") or []),
            memory_summary=str(state.get("memory_summary") or ""),
            history=list(state.get("history") or []),
            store_facts=list(state.get("store_facts") or []),
        )
        parts = list(
            complete_text_stream(
                prompt=prompt,
                credentials=credentials,
                system=ANSWER_SYSTEM_PROMPT,
            )
        )
        text = "".join(parts)
        if not text.strip():
            return {
                **state,
                "answer": strip_internal_ids(
                    _soft_fail_answer(query=user_query, has_citations=False)
                ),
                "used_mock": True,
                "citations": [],
            }
        return {**state, "answer": strip_internal_ids(text), "used_mock": False}

    return answer


def guardrail(state: AgentState) -> AgentState:
    q = state.get("query", "")
    if any(k in q for k in GUARDRAIL_KEYWORDS):
        return {
            **state,
            "blocked": True,
            "block_reason": "该问题触及安全策略，无法提供协助。",
        }
    return {**state, "blocked": False, "block_reason": ""}


def _route_by_intent(state: AgentState) -> str:
    intent = str(state.get("intent") or "career_advice").lower()
    intent = _LEGACY_INTENT_ALIASES.get(intent, intent)
    if intent == "chitchat":
        return "chitchat"
    if intent == "ambiguous":
        return "ambiguous"
    if intent == "out_of_scope":
        return "out_of_scope"
    if intent in RETRIEVE_INTENTS:
        return "legal"
    return "ambiguous"


def route_facts(state: AgentState) -> str:
    if state.get("facts_sufficient"):
        return "rewrite_issue"
    limit = state.get("max_followups")
    cap = 2 if limit is None else int(limit)
    if int(state.get("followup_rounds") or 0) >= cap:
        return "staged"
    return "followup"


def route_hits(state: AgentState) -> str:
    if state.get("retrieval_usable"):
        return "answer"
    return "no_basis"


def build_graph(
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
    top_k: int = DEFAULT_RETRIEVE_TOP_K,
    checkpointer: Any | None = None,
):
    retriever = retriever or FakeRetriever()

    def intent_node(state: AgentState) -> AgentState:
        return classify_intent(state, credentials=credentials)

    def case_node(state: AgentState) -> AgentState:
        return classify_case_type(state, credentials=credentials)

    def rewrite_node(state: AgentState) -> AgentState:
        return rewrite_issue(state, credentials=credentials)

    def no_basis_node(state: AgentState) -> AgentState:
        return prepare_legal_report(state, credentials=credentials, hit=False)

    def analyze_node(state: AgentState) -> AgentState:
        return prepare_legal_report(state, credentials=credentials, hit=True)

    g = StateGraph(AgentState)
    g.add_node("classify_intent", intent_node)
    g.add_node("classify", case_node)
    g.add_node("collect", make_collect(credentials))
    g.add_node("followup", prepare_followup)
    g.add_node("staged", prepare_staged)
    g.add_node("rewrite_issue", rewrite_node)
    g.add_node("retrieve", make_retrieve(retriever, top_k=top_k))
    g.add_node("no_basis", no_basis_node)
    g.add_node("answer", analyze_node)
    g.add_node("answer_chitchat", prepare_chitchat)
    g.add_node("answer_clarify", prepare_clarify)
    g.add_node("answer_out_of_scope", prepare_out_of_scope)
    g.add_node("guardrail", guardrail)
    g.set_entry_point("classify_intent")
    g.add_conditional_edges(
        "classify_intent",
        _route_by_intent,
        {
            "chitchat": "answer_chitchat",
            "ambiguous": "answer_clarify",
            "out_of_scope": "answer_out_of_scope",
            "legal": "classify",
        },
    )
    g.add_edge("classify", "collect")
    g.add_conditional_edges(
        "collect",
        route_facts,
        {
            "followup": "followup",
            "staged": "staged",
            "rewrite_issue": "rewrite_issue",
        },
    )
    g.add_edge("followup", "guardrail")
    g.add_edge("staged", "guardrail")
    g.add_edge("rewrite_issue", "retrieve")
    g.add_conditional_edges(
        "retrieve",
        route_hits,
        {
            "answer": "answer",
            "no_basis": "no_basis",
        },
    )
    g.add_edge("no_basis", "guardrail")
    g.add_edge("answer", "guardrail")
    g.add_edge("answer_chitchat", "guardrail")
    g.add_edge("answer_clarify", "guardrail")
    g.add_edge("answer_out_of_scope", "guardrail")
    g.add_edge("guardrail", END)
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


_STREAM_TRUNCATED_FOOTER = "（生成超时，以上内容可能不完整，可点击重试或换个问法。）"
_STREAM_LENGTH_FOOTER = "（篇幅受限，可继续追问补全）"


def _stream_answer_tokens(
    *,
    request_id: str,
    state: AgentState,
    credentials: ProviderCredentials | None,
    system: str,
    prompt: str,
    mock_text: str,
    mock_sleep: float | None,
) -> Iterator[ChatEvent | tuple[str, bool, bool]]:
    """Yield token ChatEvents; last yield is (full_text, used_mock, generation_failed)."""
    full_parts: list[str] = []
    used_mock = False
    generation_failed = False

    def _emit_text(text: str, *, as_mock: bool) -> Iterator[ChatEvent]:
        nonlocal used_mock
        used_mock = as_mock
        for piece in _iter_mock_chunks(text):
            full_parts.append(piece)
            yield ChatEvent.token(request_id, piece)
            if mock_sleep and mock_sleep > 0:
                time.sleep(mock_sleep)

    def _fallback_after_empty_stream() -> Iterator[ChatEvent]:
        nonlocal generation_failed
        generation_failed = True
        logger.info("Answer stream failed; no retry request_id=%s", request_id)
        fail_text = _soft_fail_answer(
            query=(state.get("query") or "").strip(), has_citations=False,
        )
        yield from _emit_text(fail_text, as_mock=True)

    if credentials is None:
        logger.info("LLM answer using paced mock stream (no enabled provider)")
        yield from _emit_text(mock_text, as_mock=True)
    else:
        generation_started = time.monotonic()
        got_any = False
        truncated: StreamTruncatedError | None = None
        try:
            for piece in complete_text_stream(
                prompt=prompt,
                credentials=credentials,
                system=system,
            ):
                got_any = True
                full_parts.append(piece)
                yield ChatEvent.token(request_id, piece)
        except StreamTruncatedError as exc:
            truncated = exc
        except Exception:
            logger.warning("Answer stream interrupted request_id=%s", request_id)
            truncated = StreamTruncatedError(kind="error", chars_emitted=sum(map(len, full_parts)))

        logging.getLogger("lawbot.timing").info(
            "agent_timing request_id=%s stage=generation elapsed_ms=%.2f",
            request_id, (time.monotonic() - generation_started) * 1000,
        )
        body = "".join(full_parts).strip()
        if truncated is not None:
            if body:
                note = (
                    _STREAM_LENGTH_FOOTER
                    if truncated.kind == "length"
                    else "（生成中断，以上内容可能不完整，请稍后重试。）"
                    if truncated.kind == "error"
                    else _STREAM_TRUNCATED_FOOTER
                )
                footer = f"\n\n{note}"
                full_parts.append(footer)
                yield ChatEvent.token(request_id, footer)
                logger.info(
                    "Stream truncated=true kind=%s chars=%s request_id=%s",
                    truncated.kind,
                    truncated.chars_emitted,
                    request_id,
                )
            else:
                yield from _fallback_after_empty_stream()
        elif not got_any or not body:
            yield from _fallback_after_empty_stream()

    yield ("".join(full_parts), used_mock, generation_failed)  # type: ignore[misc]


def _emit_final_trace(state: AgentState, *, answer: str) -> None:
    phase = str(state.get("phase") or "")
    cites = list(state.get("citations") or [])
    source_ids = [str(item.get("source_id") or "") for item in cites if item.get("source_id")]
    followed_up = phase == "followup" or "请补充：" in (answer or "")
    trace_step(
        "final",
        input_summary=f"phase={phase}",
        output_summary=(
            f"followup={followed_up} citations={len(cites)} "
            f"self_check={state.get('self_check_action') or '-'}"
        ),
        source_ids=source_ids,
        self_check_issues=list(state.get("self_check_issues") or []),
        action=str(state.get("self_check_action") or phase or "done"),
    )


_NODE_STATUS: dict[str, tuple[str, str]] = {
    "classify_intent": ("thinking", "正在理解问题…"),
    "classify": ("thinking", "正在理解问题…"),
    "collect": ("thinking", "正在整理问题…"),
    "rewrite_issue": ("retrieve", "正在检索…"),
    "retrieve": ("retrieve", "正在检索…"),
    "answer": ("generate", "正在生成…"),
    "no_basis": ("generate", "正在生成…"),
    "followup": ("generate", "正在生成…"),
    "staged": ("generate", "正在生成…"),
    "answer_chitchat": ("generate", "正在生成…"),
    "answer_clarify": ("generate", "正在生成…"),
    "answer_out_of_scope": ("generate", "正在生成…"),
}

# prepare_* nodes that carry stream_prompt / fixed_text — start answer tokens here (not at graph END).
_STREAM_READY_NODES = frozenset(
    {
        "answer",
        "no_basis",
        "followup",
        "staged",
        "answer_chitchat",
        "answer_clarify",
        "answer_out_of_scope",
    }
)


def _state_ready_to_stream(node_name: str, state: AgentState) -> bool:
    if str(node_name) not in _STREAM_READY_NODES:
        return False
    if (state.get("stream_prompt") or "").strip():
        return True
    if (state.get("fixed_text") or "").strip():
        return True
    phase = state.get("phase") or ""
    if phase == "report_failed" and (state.get("mock_text") or "").strip():
        return True
    return False


def _run_graph_with_status(
    graph: Any,
    invoke_state: AgentState,
    *,
    request_id: str,
    config: dict[str, Any] | None = None,
) -> Iterator[ChatEvent | tuple[str, AgentState]]:
    """Yield status events; yield ('ready', state) when prepare_* can stream; ('final', state) at END.

    Bottleneck note: time_to_first_token_ms - graph_ready_ms ≈ upstream model TTFT;
    large retrieve_ms / embed_ms → retrieval; large collect/case_type with source=llm → rules.
    """
    yield ChatEvent.status(request_id, "thinking", "正在理解问题…")
    state: AgentState = dict(invoke_state)
    last_message = "正在理解问题…"
    ready_emitted = False
    stream_kwargs: dict[str, Any] = {"stream_mode": "updates"}
    if config is not None:
        stream_kwargs["config"] = config
    for update in graph.stream(invoke_state, **stream_kwargs):
        if not isinstance(update, dict):
            continue
        for node_name, patch in update.items():
            if isinstance(patch, dict):
                state = {**state, **patch}
            mapped = _NODE_STATUS.get(str(node_name))
            if mapped and mapped[1] != last_message:
                stage, message = mapped
                last_message = message
                yield ChatEvent.status(request_id, stage, message)
            if not ready_emitted and _state_ready_to_stream(str(node_name), state):
                ready_emitted = True
                yield ("ready", dict(state))
    yield ("final", state)


def run_agent_stream(
    query: str,
    request_id: str,
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
    top_k: int = DEFAULT_RETRIEVE_TOP_K,
    *,
    mock_sleep: float | None = MOCK_CHUNK_SLEEP_S,
    history: list[dict[str, str]] | None = None,
    max_followups: int = 2,
    min_retrieve_score: float = 0.6,
    conversation_id: str | None = None,
    checkpointer: Any | None = None,
    database_url: str | None = None,
    province_hint: str | None = None,
    user_id: str | None = None,
    store_facts: list[dict[str, Any]] | None = None,
    active_resume: dict[str, Any] | None = None,
    active_jd: dict[str, Any] | None = None,
) -> Iterator[ChatEvent | AgentState]:
    """Emit status while the graph runs; start answer tokens as soon as prepare_* is ready.

    Short-term continuity: checkpointer thread_id = str(conversation_id).
    history is prompt/merge assist only — slots come from checkpoint; merge only on 请补充.
    store_facts are cross-session user memories (not law citations).
    active_resume / active_jd are parsed profiles (not RAG).
    """
    tracer = AgentTracer(request_id=request_id, conversation_id=conversation_id)
    token = bind_tracer(tracer)
    stream_t0 = time.monotonic()
    ttft_logged = False
    first_token_t0: float | None = None

    def _note_first_token(ev: ChatEvent) -> None:
        nonlocal ttft_logged, first_token_t0
        if ttft_logged or ev.type != "token":
            return
        ttft_logged = True
        first_token_t0 = time.monotonic()
        logger.info(
            "agent_timing time_to_first_token_ms=%s request_id=%s",
            int((first_token_t0 - stream_t0) * 1000),
            request_id,
        )

    def _emit_answer_body(
        state: AgentState,
    ) -> Iterator[ChatEvent | AgentState]:
        """Yield tokens/citations then final AgentState for a prepare_* ready state."""
        nonlocal first_token_t0
        phase = state.get("phase") or "analyze"

        if phase == "report_failed":
            fail_text = strip_internal_ids(
                (state.get("mock_text") or "").strip()
                or _soft_fail_answer(query=query, has_citations=False)
            )
            for piece in _iter_mock_chunks(fail_text):
                tok = ChatEvent.token(request_id, piece)
                _note_first_token(tok)
                yield tok
                if mock_sleep and mock_sleep > 0:
                    time.sleep(mock_sleep)
            failed = {
                **state,
                "request_id": request_id,
                "answer": fail_text,
                "used_mock": True,
                "blocked": False,
                "block_reason": "",
                "citations": [],
            }
            _emit_final_trace(failed, answer=fail_text)
            yield failed
            return

        fixed = strip_internal_ids((state.get("fixed_text") or "").strip())
        if phase in {"followup", "staged", "no_basis", "analyze", "chitchat"} and fixed:
            for piece in _iter_mock_chunks(fixed):
                tok = ChatEvent.token(request_id, piece)
                _note_first_token(tok)
                yield tok
                if mock_sleep and mock_sleep > 0:
                    time.sleep(mock_sleep)
            kept_citations = list(state.get("citations") or []) if phase == "analyze" else []
            if phase == "analyze":
                for citation in kept_citations:
                    yield ChatEvent.citation(request_id, Citation.model_validate(citation))
            done = {
                **state,
                "request_id": request_id,
                "answer": fixed,
                "used_mock": bool(state.get("used_mock", True)),
                "blocked": False,
                "block_reason": "",
                "citations": kept_citations,
            }
            _emit_final_trace(done, answer=fixed)
            yield done
            return

        full = ""
        used_mock = False
        generation_failed = False
        for item in _stream_answer_tokens(
            request_id=request_id,
            state=state,
            credentials=credentials,
            system=state.get("stream_system") or ANSWER_SYSTEM_PROMPT,
            prompt=state.get("stream_prompt") or "",
            mock_text=state.get("mock_text") or _mock_answer(state),
            mock_sleep=mock_sleep,
        ):
            if isinstance(item, tuple):
                if len(item) >= 3:
                    full, used_mock, generation_failed = item[0], item[1], item[2]
                else:
                    full, used_mock = item[0], item[1]
                    generation_failed = False
            else:
                _note_first_token(item)
                yield item

        if first_token_t0 is not None:
            logger.info(
                "agent_timing answer_stream_ms=%s request_id=%s",
                int((time.monotonic() - first_token_t0) * 1000),
                request_id,
            )

        # Rule-only self-check after streamed legal / no-basis answer.
        out_state: AgentState = state
        if phase in {"analyze", "no_basis"} and full.strip() and not generation_failed:
            cite_list = list(state.get("citations") or []) if phase == "analyze" else []
            checked = run_self_check(
                full,
                cite_list,
                list(state.get("law_hits") or []) if phase == "analyze" else [],
                None,
            )
            full = strip_internal_ids(checked.text)
            if state.get("province") and LOCAL_LAW_NOTE not in full:
                if "## 风险提示" in full or "## 注意" in full:
                    pass
                else:
                    full = f"{full.rstrip()}\n\n{LOCAL_LAW_NOTE}"
            final_cites = (
                []
                if phase == "no_basis" or checked.action == "downgrade"
                else list(checked.citations)
            )
            out_state = {
                **state,
                "self_check_passed": checked.passed,
                "self_check_issues": list(checked.issues),
                "self_check_action": checked.action,
                "citations": final_cites,
            }
        elif generation_failed:
            out_state = {**state, "citations": []}
        else:
            full = strip_internal_ids(full)

        if phase == "analyze" and not generation_failed:
            for citation in out_state.get("citations") or []:
                yield ChatEvent.citation(request_id, Citation.model_validate(citation))

        streamed = {
            **out_state,
            "request_id": request_id,
            "answer": full,
            "used_mock": used_mock,
            "blocked": False,
            "block_reason": "",
            "citations": [] if generation_failed else list(out_state.get("citations") or []),
        }
        _emit_final_trace(streamed, answer=full)
        yield streamed

    try:
        if any(k in query for k in GUARDRAIL_KEYWORDS):
            trace_step(
                "guardrail",
                input_summary=privacy_summary(query),
                output_summary="blocked",
                action="refuse",
            )
            yield ChatEvent.error(request_id, "guardrail_blocked", "该问题触及安全策略，无法提供协助。")
            final_blocked: AgentState = {
                "query": query,
                "request_id": request_id,
                "blocked": True,
                "block_reason": "该问题触及安全策略，无法提供协助。",
                "answer": "",
                "citations": [],
            }
            if conversation_id:
                final_blocked["conversation_id"] = conversation_id
            _emit_final_trace(final_blocked, answer="")
            yield final_blocked
            return

        retriever = retriever or FakeRetriever()
        # Persist only when the caller wants a conversation thread.
        if checkpointer is None and conversation_id:
            checkpointer = get_checkpointer(database_url)
        graph = build_graph(
            retriever, credentials, top_k=top_k, checkpointer=checkpointer
        )
        # Do not pass slot fields — checkpoint retains confirmed_facts / followup_rounds.
        # thread_id = str(conversation_id); new chat = new conversation = new thread.
        invoke_state: AgentState = {
            "query": query,
            "request_id": request_id,
            "citations": [],
            "answer": "",
            "law_hits": [],
            "tool_trace": [],
            "max_followups": max_followups,
            "min_retrieve_score": min_retrieve_score,
            "store_facts": list(store_facts or []),
        }
        if history:
            # Prompt / 请补充 detection assist only; slots authoritative from checkpoint.
            invoke_state["history"] = list(history)
        if conversation_id:
            invoke_state["conversation_id"] = conversation_id
        if province_hint:
            invoke_state["province"] = province_hint
        if user_id:
            invoke_state["user_id"] = str(user_id)
        if active_resume:
            invoke_state["active_resume"] = dict(active_resume)
        if active_jd:
            invoke_state["active_jd"] = dict(active_jd)
        stream_config = None
        if checkpointer is not None:
            thread_id = str(conversation_id or request_id)
            stream_config = {"configurable": {"thread_id": thread_id}}

        state: AgentState = dict(invoke_state)
        answer_emitted = False
        final_result: AgentState | None = None

        for item in _run_graph_with_status(
            graph, invoke_state, request_id=request_id, config=stream_config
        ):
            if isinstance(item, ChatEvent):
                yield item
                continue
            kind, patch_state = item
            if kind == "ready" and not answer_emitted:
                state = patch_state
                logger.info(
                    "agent_timing graph_ready_ms=%s request_id=%s phase=%s",
                    int((time.monotonic() - stream_t0) * 1000),
                    request_id,
                    state.get("phase") or "-",
                )
                # Start tokens as soon as prepare_* is ready (do not wait for graph END).
                for out in _emit_answer_body(state):
                    if isinstance(out, ChatEvent):
                        yield out
                    else:
                        final_result = out
                        answer_emitted = True
            elif kind == "final":
                state = {**state, **patch_state}

        if state.get("blocked"):
            reason = state.get("block_reason") or "该问题触及安全策略，无法提供协助。"
            # If we already streamed, still surface block for safety (rare; entry guard covers keywords).
            if not answer_emitted:
                yield ChatEvent.error(request_id, "guardrail_blocked", reason)
            blocked_state = {
                **state,
                "query": query,
                "request_id": request_id,
                "blocked": True,
                "block_reason": reason,
                "answer": "",
                "citations": [],
            }
            _emit_final_trace(blocked_state, answer="")
            yield blocked_state
            return

        if not answer_emitted:
            for out in _emit_answer_body(state):
                if isinstance(out, ChatEvent):
                    yield out
                else:
                    final_result = out

        if final_result is not None:
            # Merge late graph fields (e.g. guardrail) without wiping the answer.
            yield {
                **state,
                **final_result,
                "blocked": False,
                "block_reason": "",
            }
    finally:
        # StreamingResponse may resume the generator in another ContextVar context.
        try:
            reset_tracer(token)
        except ValueError:
            logger.debug("agent tracer ContextVar already detached", exc_info=True)
