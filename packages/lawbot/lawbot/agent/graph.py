from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from lawbot.agent.citations import (
    format_basis_line,
    needs_unverified_fallback,
    repair_citations,
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
    CHITCHAT_SYSTEM_PROMPT,
    CLARIFY_SYSTEM_PROMPT,
    FOLLOWUP_SYSTEM_PROMPT,
    INTENT_CLASSIFY_SYSTEM_PROMPT,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    STAGED_SYSTEM_PROMPT,
    build_answer_user_prompt,
    build_chitchat_user_prompt,
    build_clarify_user_prompt,
    build_followup_user_prompt,
    build_intent_classify_user_prompt,
    build_staged_user_prompt,
    build_out_of_scope_user_prompt,
    build_rewrite_user_prompt,
)
from lawbot.agent.tools import ToolContext, execute_tool
from lawbot.domain.schemas import ChatEvent, Citation
from lawbot.llm.client import ProviderCredentials, complete_text, complete_text_stream
from lawbot.rag.base import Retriever
from lawbot.rag.fake import FakeRetriever

logger = logging.getLogger(__name__)

GUARDRAIL_KEYWORDS = ("如何制造炸弹", "洗钱方法", "伪造证件")
DEFAULT_RETRIEVE_TOP_K = 5
MOCK_CHUNK_SIZE = 16
MOCK_CHUNK_SLEEP_S = 0.015

Intent = Literal["chitchat", "legal", "ambiguous", "out_of_scope"]

CHITCHAT_PHRASES = (
    "你好",
    "您好",
    "嗨",
    "hi",
    "hello",
    "在吗",
    "在不在",
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
    "写代码",
    "编程",
    "python",
    "javascript",
    "java代码",
    "算法",
    "排序",
    "leetcode",
    "bug",
    "debug",
    "菜谱",
    "红烧肉",
    "怎么做菜",
    "烹饪",
    "旅游攻略",
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
)
LEGAL_KEYWORDS = (
    "违法",
    "怎么办",
    "赔偿",
    "起诉",
    "合同",
    "劳动",
    "工资",
    "离婚",
    "违约",
    "仲裁",
    "诉讼",
    "权利",
    "义务",
    "解雇",
    "辞退",
    "拖欠",
    "解除",
    "纠纷",
    "遗嘱",
    "继承",
    "侵权",
    "借贷",
    "房屋",
    "租房",
    "婚姻",
    "抚养",
    "赡养",
)
LEGAL_ORAL_SIGNALS = (
    "打了",
    "被打",
    "打人",
    "动手",
    "讹",
    "索赔",
    "报警",
    "欠钱",
    "裁员",
    "被裁",
    "家暴",
    "被骗",
    "吵架",
    "受伤",
    "医药费",
    "要钱",
    "调解",
    "被欠",
    "不给钱",
    "打伤",
    "骨折",
    "住院",
    "派出所",
    "勒索",
    "敲诈",
    "开车",
    "追尾",
    "撞人",
    "交通事故",
    "撞车",
    "车祸",
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
VALID_INTENTS = frozenset({"chitchat", "legal", "ambiguous", "out_of_scope"})


class AgentState(TypedDict, total=False):
    query: str
    request_id: str
    intent: str
    case_type: str
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


def _normalize_query(query: str) -> str:
    return (query or "").strip()


def _has_legal_signal(query: str) -> bool:
    return any(k in query for k in LEGAL_KEYWORDS) or any(k in query for k in LEGAL_ORAL_SIGNALS)


def _rule_intent(query: str) -> Intent | None:
    q = _normalize_query(query)
    if not q:
        return "ambiguous"

    q_lower = q.lower()
    compact = re.sub(r"[\s\,\.\!\?，。！？、~～]+", "", q_lower)
    has_legal = _has_legal_signal(q)

    if any(p.lower() in q_lower or p.lower() in compact for p in CAPABILITY_PHRASES):
        return "chitchat"

    if not has_legal and len(q) <= SHORT_QUERY_MAX_LEN:
        if compact in {p.lower() for p in CHITCHAT_PHRASES}:
            return "chitchat"
        if any(compact == p.lower() or compact.startswith(p.lower()) for p in CHITCHAT_PHRASES):
            if len(compact) <= SHORT_QUERY_MAX_LEN:
                return "chitchat"

    has_oos = any(s.lower() in q_lower for s in OUT_OF_SCOPE_SIGNALS)
    if has_oos and not has_legal:
        return "out_of_scope"

    if has_legal:
        return "legal"

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
    if len(q) <= 4 and not _has_legal_signal(q):
        return "ambiguous"
    return "legal"


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
    if intent in VALID_INTENTS:
        return intent  # type: ignore[return-value]
    return None


def classify_intent(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    query = _normalize_query(state.get("query") or "")
    ruled = _rule_intent(query)
    if ruled is not None:
        out = {**state, "intent": ruled}
        trace_step(
            "classify_intent",
            input_summary=privacy_summary(query),
            output_summary=f"intent={ruled}",
        )
        return out

    if credentials is not None:
        try:
            raw = complete_text(
                prompt=build_intent_classify_user_prompt(query=query),
                credentials=credentials,
                system=INTENT_CLASSIFY_SYSTEM_PROMPT,
            )
            parsed = _parse_intent_json(raw)
            if parsed is not None:
                out = {**state, "intent": parsed}
                trace_step(
                    "classify_intent",
                    input_summary=privacy_summary(query),
                    output_summary=f"intent={parsed}",
                )
                return out
        except Exception:
            logger.exception("intent LLM classify failed; using fallback rules")

    intent = _fallback_intent(query)
    out = {**state, "intent": intent}
    trace_step(
        "classify_intent",
        input_summary=privacy_summary(query),
        output_summary=f"intent={intent}",
    )
    return out


def classify(state: AgentState) -> AgentState:
    q = state["query"]
    if any(k in q for k in ("劳动", "工资", "解雇", "裁员", "被裁", "拖欠")):
        case_type = "labor"
    elif any(k in q for k in ("合同", "违约")):
        case_type = "contract"
    elif any(
        k in q
        for k in ("打了", "被打", "打人", "讹", "受伤", "家暴", "赔偿", "追尾", "撞人", "交通事故", "车祸")
    ):
        case_type = "tort"
    else:
        case_type = "general"
    return {**state, "case_type": case_type}


_SLOT_RULES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "labor": [
        ("当事人", ("公司", "单位", "老板", "用人单位")),
        ("争议事实", ("拖欠", "工资", "解雇", "辞退", "裁员", "加班", "社保", "工伤")),
    ],
    "tort": [
        ("伤害或事故", ("打", "撞", "受伤", "家暴", "追尾", "车祸")),
    ],
    "contract": [
        ("合同或欠款关系", ("合同", "欠", "借")),
        ("争议事实", ("违约", "不付", "不还", "拖欠", "没给")),
    ],
}

_GENERAL_EVENTS = (
    "拖欠",
    "工资",
    "解雇",
    "辞退",
    "裁员",
    "加班",
    "社保",
    "工伤",
    "打",
    "撞",
    "受伤",
    "家暴",
    "追尾",
    "车祸",
    "合同",
    "欠",
    "借",
    "违约",
    "不付",
    "不还",
    "离婚",
    "继承",
    "诈骗",
    "赔偿",
    "租",
    "借款",
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
    for name, keys in rules:
        if any(key in corpus for key in keys):
            confirmed.append(name)
        else:
            missing.append(name)
    return missing, confirmed


def _merge_confirmed(case_type: str, query: str, prior_confirmed: list[str]) -> tuple[list[str], list[str]]:
    """Merge checkpoint confirmed slots with slots found in this turn's query only."""
    _missing_now, confirmed_now = _assess_facts(case_type, query)
    confirmed: list[str] = []
    for name in list(prior_confirmed) + list(confirmed_now):
        if name and name not in confirmed:
            confirmed.append(name)
    rules = _SLOT_RULES.get(case_type)
    if not rules:
        if confirmed:
            return [], confirmed
        return ["具体事件"], []
    slot_names = [name for name, _keys in rules]
    missing = [name for name in slot_names if name not in confirmed]
    return missing, confirmed


def collect(state: AgentState) -> AgentState:
    query = state.get("query") or ""
    case_type = state.get("case_type") or "general"
    prior_confirmed = list(state.get("confirmed_facts") or [])
    prior_rounds = int(state.get("followup_rounds") or 0)
    # Bootstrap from history only when checkpoint has no confirmed slots yet
    if not prior_confirmed and state.get("history"):
        corpus = _user_corpus(query, list(state.get("history") or []))
        missing, confirmed = _assess_facts(case_type, corpus)
        prior_rounds = max(prior_rounds, _count_followups(list(state.get("history") or [])))
    else:
        missing, confirmed = _merge_confirmed(case_type, query, prior_confirmed)
    province = extract_province(query) or state.get("province") or ""
    summary = f"已确认：{'、'.join(confirmed) or '（无）'}；案由 {case_type}"
    if province:
        summary += f"；地区 {province}"
    collected = f"{summary}\n本轮：{query.strip()}"
    out = {
        **state,
        "collected": collected,
        "dialogue": _dialogue(query, None),
        "missing_facts": missing,
        "confirmed_facts": confirmed,
        "memory_summary": summary,
        "facts_sufficient": not missing,
        "followup_rounds": prior_rounds,
        "province": province,
    }
    trace_step(
        "collect",
        input_summary=privacy_summary(query),
        output_summary=(
            f"case={case_type} sufficient={not missing} "
            f"missing={','.join(missing) or '无'} confirmed={','.join(confirmed) or '无'}"
        ),
    )
    return out


def _heuristic_rewrite(query: str) -> tuple[str, str]:
    q = _normalize_query(query)
    if any(k in q for k in ("打了", "被打", "打人", "动手", "讹", "受伤", "打伤", "家暴")):
        plain = "被人打了，想依法维权或索赔（口语里说的「讹」按合法赔偿理解）。"
        search = "故意伤害 民事赔偿 报警"
        return search, plain
    if any(k in q for k in ("开车", "追尾", "撞人", "交通事故", "撞车", "车祸", "人伤")):
        return "交通事故 人身损害 赔偿", "发生交通事故/人身损害，想了解怎么索赔或责任划分。"
    if any(k in q for k in ("工资", "拖欠", "被裁", "裁员", "解雇", "辞退")):
        return "劳动报酬 解除劳动合同", "劳动方面发生了争议，想了解怎么维权。"
    if any(k in q for k in ("离婚", "抚养", "赡养", "家暴")):
        return "婚姻家庭 离婚 抚养", "婚姻家庭方面的纠纷，想了解怎么处理。"
    if any(k in q for k in ("合同", "违约", "欠钱", "借贷")):
        return "合同违约 民事赔偿", "合同或欠款纠纷，想了解怎么要回钱或维权。"
    return q, f"用户说：{q[:80]}"


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


def rewrite_issue(
    state: AgentState,
    credentials: ProviderCredentials | None = None,
) -> AgentState:
    query = _normalize_query(state.get("collected") or state.get("query") or "")
    search, plain = _heuristic_rewrite(query)
    if credentials is not None:
        try:
            raw = complete_text(
                prompt=build_rewrite_user_prompt(query=query),
                credentials=credentials,
                system=REWRITE_SYSTEM_PROMPT,
            )
            parsed = _parse_rewrite_json(raw)
            if parsed is not None:
                search, plain = parsed
        except Exception:
            logger.exception("rewrite_issue LLM failed; using heuristics")
    return {
        **state,
        "search_query": search,
        "user_issue_plain": plain,
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
    }


def make_retrieve(retriever: Retriever, top_k: int = DEFAULT_RETRIEVE_TOP_K):
    def retrieve(state: AgentState) -> AgentState:
        query = (state.get("search_query") or state.get("collected") or state.get("query") or "").strip()
        ctx = ToolContext(retriever=retriever, tool_trace=list(state.get("tool_trace") or []))
        outcome = execute_tool("search_laws", {"query": query, "top_k": top_k}, ctx)
        hits = list(outcome.output or []) if outcome.ok else []
        raw_threshold = state.get("min_retrieve_score")
        threshold = 0.6 if raw_threshold is None else float(raw_threshold)
        top_score = max((float(hit.get("score") or 0.0) for hit in hits), default=0.0)
        usable = bool(hits) and top_score >= threshold
        citations = [_citation_from_hit(hit) for hit in hits] if usable else []
        source_ids = [str(hit.get("source_id") or "") for hit in hits if hit.get("source_id")]
        trace_step(
            "search_laws",
            input_summary=privacy_summary(query),
            output_summary=f"hits={len(hits)} usable={usable} top={top_score:.3f}",
            source_ids=source_ids,
        )
        return {
            **state,
            "citations": citations,
            "law_hits": hits,
            "retrieval_usable": usable,
            "tool_trace": ctx.tool_trace,
        }

    return retrieve


def _missing_label(state: AgentState) -> str:
    missing = state.get("missing_facts") or ["关键事实"]
    return "、".join(missing)


def prepare_followup(state: AgentState) -> AgentState:
    names = _missing_label(state)
    dialogue = state.get("dialogue") or _dialogue(state.get("query") or "", state.get("history"))
    missing = [item.strip() for item in (state.get("missing_facts") or []) if str(item).strip()]
    if not missing:
        missing = ["关键事实"]
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


def _heuristic_report_args(state: AgentState, *, hit: bool) -> dict[str, str]:
    if not hit:
        return {
            "legal_basis": "未检索到明确依据。不能据此引用具体法条。",
            "analysis": "现有说法还对不上明确的法律依据。",
            "advice": "可以先报警、固定伤情和损失证据，再依法请求赔偿。",
            "risk": "不要用违法方式处理，也不要自行编造法条。",
        }
    lines = [format_basis_line(citation) for citation in (state.get("citations") or [])[:3]]
    basis = "\n".join(lines) if lines else "检索到相关规定，请对照引用卡片。"
    issue = (state.get("user_issue_plain") or state.get("query") or "所述争议")[:80]
    return {
        "legal_basis": basis,
        "analysis": f"结合「{issue}」，是否成立仍取决于事实细节。",
        "advice": "核对书面证据，并按合法途径协商、投诉或申请仲裁。",
        "risk": "注意时效、通知和证据，重大决定前咨询执业律师。",
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
    cite_note = "（无）" if not cites else json.dumps(cites, ensure_ascii=False)
    prompt = (
        "只输出 JSON，键为 legal_basis、analysis、advice、risk，值都是非空字符串。\n"
        "法律依据只能使用下面检索结果里的法规名和条号，并标注效力。\n"
        f"问题：{state.get('query') or ''}\n"
        f"检索结果：{cite_note}\n"
    )
    if doubtful:
        banned = "、".join(f"《{law}》{article}" for law, article in doubtful)
        prompt += f"以下引用存疑，不要再写：{banned}。\n"
    if not cites:
        prompt += "未检索到明确依据。legal_basis 必须写明未检索到明确依据，禁止编造法条编号。\n"
    raw = complete_text(
        prompt=prompt,
        credentials=credentials,
        system="你只输出一个 JSON 对象，键只能是 legal_basis、analysis、advice、risk。",
    )
    return _parse_report_args(raw)


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

    def _render(args: dict[str, Any]) -> tuple[bool, str]:
        outcome = execute_tool("emit_legal_report", args, ctx)
        if not outcome.ok:
            return False, ""
        return True, str(outcome.output or "")

    used_mock = credentials is None
    if credentials is None:
        ok, text = _render(_heuristic_report_args(report_state, hit=use_hits))
    else:
        try:
            raw_args = _model_report_args(report_state, credentials)
        except Exception:
            logger.exception("legal report args failed")
            raw_args = {}
        ok, text = _render(raw_args)
    if not ok:
        fail = _soft_fail_answer(query=state.get("query") or "", has_citations=bool(citations))
        trace_step(
            "emit_legal_report",
            input_summary=f"hit={use_hits}",
            output_summary="report_failed",
            action="fail",
        )
        return {
            **state,
            "phase": "report_failed",
            "citations": citations,
            "dialogue": dialogue,
            "fixed_text": "",
            "mock_text": fail,
            "tool_trace": ctx.tool_trace,
            "used_mock": True,
            "retrieval_usable": use_hits,
        }

    trace_step(
        "emit_legal_report",
        input_summary=f"hit={use_hits} cites={len(citations)}",
        output_summary=redact_text(text),
    )

    def _regenerate(marked: str, doubtful: list[tuple[str, str]], hits: list[dict[str, Any]]) -> str:
        if not use_hits:
            return marked
        if credentials is None:
            draft: AgentState = {**report_state, "citations": list(supported_index(hits).values())}
            rebuilt_ok, rebuilt = _render(_heuristic_report_args(draft, hit=bool(draft["citations"])))
            return rebuilt if rebuilt_ok else marked
        try:
            raw_args = _model_report_args(report_state, credentials, doubtful=doubtful)
        except Exception:
            logger.exception("legal report regenerate failed")
            raw_args = {}
        rebuilt_ok, rebuilt = _render(raw_args)
        return rebuilt if rebuilt_ok else marked

    repaired = repair_citations(text, citations, law_hits, _regenerate)
    checked = run_self_check(
        repaired.text,
        repaired.citations if use_hits else [],
        law_hits if use_hits else [],
        credentials,
    )
    final_text = checked.text
    if state.get("province") and LOCAL_LAW_NOTE not in final_text:
        if "## 风险提示" in final_text:
            final_text = final_text.replace(
                "## 风险提示",
                f"## 风险提示\n\n{LOCAL_LAW_NOTE}",
                1,
            )
        else:
            final_text = f"{final_text.rstrip()}\n\n{LOCAL_LAW_NOTE}"
    final_citations = list(checked.citations) if use_hits else []
    if checked.action == "downgrade":
        final_citations = []
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
        "tool_trace": ctx.tool_trace,
        "used_mock": used_mock,
        "retrieval_usable": bool(final_citations),
        "self_check_passed": checked.passed,
        "self_check_issues": list(checked.issues),
        "self_check_action": checked.action,
    }


def prepare_chitchat(state: AgentState) -> AgentState:
    query = (state.get("query") or "").strip()
    return {
        **state,
        "collected": query,
        "citations": [],
        "phase": "chitchat",
        "dialogue": state.get("dialogue") or _dialogue(query, state.get("history")),
        "fixed_text": "",
        "mock_text": _mock_chitchat(query),
        "stream_system": CHITCHAT_SYSTEM_PROMPT,
        "stream_prompt": build_chitchat_user_prompt(query=query),
    }


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
        f"你好！我是 **LawBot** 法律咨询助手，聚焦中国法域法律咨询。"
        f"你可以直接用大白话说说遇到的事（比如被欠薪、被打、离婚纠纷），不必说法律术语；"
        f"当前收到的是「{query[:20] or '问候'}」。"
    )


def _mock_clarify(query: str) -> str:
    return (
        f"根据你说的「{query[:40] or '……'}」，我理解你可能想咨询，但目前还不太清楚具体发生了什么。"
        f"能再用一句话说一下：**发生了什么事、你最想解决什么**吗？"
        f"（比如有没有受伤、是否已报警、对方是谁——选一个你方便说的就行。）"
    )


def _mock_out_of_scope(query: str) -> str:
    return (
        f"抱歉，我无法协助「{query[:40] or '该请求'}」这类非法律咨询事项。"
        f"我是 **LawBot**，聚焦中国法域**法律咨询**。"
        f"如有被欠薪、被打、合同纠纷等，欢迎用大白话直接说。"
    )


def _soft_fail_answer(*, query: str, has_citations: bool) -> str:
    """Neutral short text when LLM stream fails despite credentials."""
    cite = "当前未检索到直接依据。" if not has_citations else "已检索到相关条文，但模型暂时无法生成完整答复。"
    return (
        f"模型暂时无法生成回复，请稍后重试。{cite}\n"
        f"你的问题是「{query[:40]}」。紧急情况请寻求执业律师或办案机关。"
    )


def _mock_answer(state: AgentState) -> str:
    intent = state.get("intent") or "legal"
    query = state.get("collected") or state.get("query") or ""
    issue = state.get("user_issue_plain") or query

    if intent == "chitchat":
        return _mock_chitchat(query)
    if intent == "ambiguous":
        return _mock_clarify(query)
    if intent == "out_of_scope":
        return _mock_out_of_scope(query)

    cites = state.get("citations") or []
    oral_hurt = any(k in query for k in ("打了", "被打", "打人", "讹", "受伤", "家暴"))

    if oral_hurt:
        cite_note = (
            "结合检索到的相关规定，具体能否主张还要看伤情鉴定与证据。"
            if cites
            else "当前**未检索到直接依据**；以下为无模型时的简短合法路径提示。"
        )
        return (
            f"## 简单说\n\n"
            f"你被人打了、想要个说法或补偿，这很常见；"
            f"建议走**合法维权**（报警、固定伤情、索赔），不要用违法方式「讹」人。\n\n"
            f"## 你可以怎么做\n\n"
            f"- 尽快**报警**并保留现场/聊天记录；\n"
            f"- 就医并保留病历、发票，必要时做法医鉴定；\n"
            f"- 可通过调解或民事诉讼主张合理赔偿（医疗费、误工等）。\n\n"
            f"## 法律上大概怎么看\n\n"
            f"{cite_note}\n"
            f"白话归纳：{issue[:80]}\n\n"
            f"## 注意\n\n"
            f"- 「讹」如果变成敲诈勒索会违法；请坚持合法索赔；\n"
            f"- 证据越早固定越好。\n"
            f"- 后台未启用模型供应商时仅提供此简短提示。\n\n"
            f"## 声明\n\n"
            f"本回复为系统**模拟回复**，不构成正式法律意见；紧急情况请报警或寻求执业律师；"
            f"电子文本以官方发布为准。"
        )

    if not cites:
        return (
            f"当前**未配置可用模型供应商**，且**未检索到直接依据**，"
            f"无法就「{query[:40]}」生成贴题分析。\n\n"
            f"请在 Admin 启用 LLM 供应商，或导入知识库后再试。"
            f"紧急情况请寻求执业律师或办案机关。"
        )

    ref_items = []
    for c in cites[:3]:
        law = c.get("law_name") or "相关规定"
        article = c.get("article_no") or ""
        text = (c.get("text") or "")[:80]
        ref_items.append(f"- **《{law}》{article}**：{text}…")
    refs_md = "\n".join(ref_items)
    return (
        f"## 简单说\n\n"
        f"结合你说的「{query[:40]}」，可以先对照检索到的规定评估可行路径，"
        f"是否成立仍取决于事实细节。\n\n"
        f"## 你可以怎么做\n\n"
        f"- 核对关键事实与书面证据；\n"
        f"- 按合法途径协商、投诉或起诉/仲裁；\n"
        f"- 重大处分前建议咨询执业律师。\n\n"
        f"## 法律上大概怎么看\n\n"
        f"{refs_md}\n\n"
        f"> 完整条文见引用卡片。白话归纳：{issue[:80]}\n\n"
        f"## 注意\n\n"
        f"- 注意催告、通知与时效。\n\n"
        f"## 声明\n\n"
        f"本回复为系统**模拟回复**，不构成正式法律意见；紧急情况请寻求执业律师或办案机关；"
        f"电子文本以官方发布为准。"
    )


def _iter_mock_chunks(text: str, chunk_size: int = MOCK_CHUNK_SIZE) -> Iterator[str]:
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


def make_answer(credentials: ProviderCredentials | None):
    """Legal-path answer node (colloquial template)."""

    def answer(state: AgentState) -> AgentState:
        legal_state = {**state, "intent": state.get("intent") or "legal"}
        if credentials is None:
            logger.info("LLM answer using mock stream (no enabled provider)")
            return {**state, "answer": _mock_answer(legal_state), "used_mock": True}

        query = state.get("collected") or state.get("query") or ""
        cites = state.get("citations") or []
        prompt = build_answer_user_prompt(
            query=query,
            case_type=state.get("case_type") or "general",
            citations=cites,
            user_issue_plain=state.get("user_issue_plain"),
            search_query=state.get("search_query"),
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
            logger.info("LiteLLM empty/failed; soft-fail without off-topic mock")
            return {
                **state,
                "answer": _soft_fail_answer(query=query, has_citations=bool(cites)),
                "used_mock": True,
            }
        return {**state, "answer": text, "used_mock": False}

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
    intent = state.get("intent") or "legal"
    if intent == "chitchat":
        return "chitchat"
    if intent == "ambiguous":
        return "ambiguous"
    if intent == "out_of_scope":
        return "out_of_scope"
    return "legal"


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

    def rewrite_node(state: AgentState) -> AgentState:
        return rewrite_issue(state, credentials=credentials)

    def no_basis_node(state: AgentState) -> AgentState:
        return prepare_legal_report(state, credentials=credentials, hit=False)

    def analyze_node(state: AgentState) -> AgentState:
        return prepare_legal_report(state, credentials=credentials, hit=True)

    g = StateGraph(AgentState)
    g.add_node("classify_intent", intent_node)
    g.add_node("classify", classify)
    g.add_node("collect", collect)
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


def _stream_answer_tokens(
    *,
    request_id: str,
    state: AgentState,
    credentials: ProviderCredentials | None,
    system: str,
    prompt: str,
    mock_text: str,
    mock_sleep: float | None,
) -> Iterator[ChatEvent | tuple[str, bool]]:
    """Yield token ChatEvents; last yield is (full_text, used_mock)."""
    full_parts: list[str] = []
    used_mock = False

    def _emit_text(text: str, *, as_mock: bool) -> Iterator[ChatEvent]:
        nonlocal used_mock
        used_mock = as_mock
        for piece in _iter_mock_chunks(text):
            full_parts.append(piece)
            yield ChatEvent.token(request_id, piece)
            if mock_sleep and mock_sleep > 0:
                time.sleep(mock_sleep)

    if credentials is None:
        logger.info("LLM answer using paced mock stream (no enabled provider)")
        yield from _emit_text(mock_text, as_mock=True)
    else:
        got_any = False
        try:
            for piece in complete_text_stream(
                prompt=prompt,
                credentials=credentials,
                system=system,
            ):
                got_any = True
                full_parts.append(piece)
                yield ChatEvent.token(request_id, piece)
        except Exception:
            logger.exception("Stream generation failed; soft-fail without off-topic mock")
            got_any = False
            full_parts.clear()

        if not got_any or not "".join(full_parts).strip():
            logger.info("LiteLLM stream empty/failed; soft-fail without off-topic mock")
            full_parts.clear()
            query = state.get("collected") or state.get("query") or ""
            cites = state.get("citations") or []
            yield from _emit_text(
                _soft_fail_answer(query=query, has_citations=bool(cites)),
                as_mock=True,
            )

    yield ("".join(full_parts), used_mock)  # type: ignore[misc]


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
) -> Iterator[ChatEvent | AgentState]:
    """Graph picks the phase; tokens are streamed only after the graph returns."""
    tracer = AgentTracer(request_id=request_id, conversation_id=conversation_id)
    token = bind_tracer(tracer)
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
        invoke_state: AgentState = {
            "query": query,
            "request_id": request_id,
            "citations": [],
            "answer": "",
            "law_hits": [],
            "tool_trace": [],
            "max_followups": max_followups,
            "min_retrieve_score": min_retrieve_score,
        }
        if history:
            invoke_state["history"] = list(history)
        if conversation_id:
            invoke_state["conversation_id"] = conversation_id
        if province_hint:
            invoke_state["province"] = province_hint
        if checkpointer is not None:
            thread_id = str(conversation_id or request_id)
            state = graph.invoke(
                invoke_state,
                config={"configurable": {"thread_id": thread_id}},
            )
        else:
            state = graph.invoke(invoke_state)
        if state.get("blocked"):
            reason = state.get("block_reason") or "该问题触及安全策略，无法提供协助。"
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

        phase = state.get("phase") or "analyze"
        if phase == "analyze":
            for citation in state.get("citations") or []:
                yield ChatEvent.citation(request_id, Citation.model_validate(citation))

        if phase == "report_failed":
            fail_text = (state.get("mock_text") or "").strip() or _soft_fail_answer(
                query=query, has_citations=bool(state.get("citations"))
            )
            for piece in _iter_mock_chunks(fail_text):
                yield ChatEvent.token(request_id, piece)
                if mock_sleep and mock_sleep > 0:
                    time.sleep(mock_sleep)
            failed = {
                **state,
                "request_id": request_id,
                "answer": fail_text,
                "used_mock": True,
                "blocked": False,
                "block_reason": "",
            }
            _emit_final_trace(failed, answer=fail_text)
            yield failed
            return

        fixed = (state.get("fixed_text") or "").strip()
        if phase in {"followup", "staged", "no_basis", "analyze"} and fixed:
            for piece in _iter_mock_chunks(fixed):
                yield ChatEvent.token(request_id, piece)
                if mock_sleep and mock_sleep > 0:
                    time.sleep(mock_sleep)
            kept_citations = list(state.get("citations") or []) if phase == "analyze" else []
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
                full, used_mock = item
            else:
                yield item

        streamed = {
            **state,
            "request_id": request_id,
            "answer": full,
            "used_mock": used_mock,
            "blocked": False,
            "block_reason": "",
        }
        _emit_final_trace(streamed, answer=full)
        yield streamed
    finally:
        reset_tracer(token)
