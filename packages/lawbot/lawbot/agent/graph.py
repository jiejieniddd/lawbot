from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from lawbot.agent.prompts import (
    ANSWER_SYSTEM_PROMPT,
    CHITCHAT_SYSTEM_PROMPT,
    CLARIFY_SYSTEM_PROMPT,
    INTENT_CLASSIFY_SYSTEM_PROMPT,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    build_answer_user_prompt,
    build_chitchat_user_prompt,
    build_clarify_user_prompt,
    build_intent_classify_user_prompt,
    build_out_of_scope_user_prompt,
    build_rewrite_user_prompt,
)
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
    answer: str
    blocked: bool
    block_reason: str
    used_mock: bool


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
        return {**state, "intent": ruled}

    if credentials is not None:
        try:
            raw = complete_text(
                prompt=build_intent_classify_user_prompt(query=query),
                credentials=credentials,
                system=INTENT_CLASSIFY_SYSTEM_PROMPT,
            )
            parsed = _parse_intent_json(raw)
            if parsed is not None:
                return {**state, "intent": parsed}
        except Exception:
            logger.exception("intent LLM classify failed; using fallback rules")

    return {**state, "intent": _fallback_intent(query)}


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


def collect(state: AgentState) -> AgentState:
    return {**state, "collected": state["query"].strip()}


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


def make_retrieve(retriever: Retriever, top_k: int = DEFAULT_RETRIEVE_TOP_K):
    def retrieve(state: AgentState) -> AgentState:
        q = state.get("search_query") or state.get("collected") or state.get("query") or ""
        chunks = retriever.retrieve(q, top_k=top_k)
        citations = [c.citation.model_dump() for c in chunks]
        return {**state, "citations": citations}

    return retrieve


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


def make_answer_chitchat(credentials: ProviderCredentials | None):
    def answer(state: AgentState) -> AgentState:
        query = state.get("collected") or state.get("query") or ""
        mock = _mock_chitchat(query)
        if credentials is None:
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        parts = list(
            complete_text_stream(
                prompt=build_chitchat_user_prompt(query=query),
                credentials=credentials,
                system=CHITCHAT_SYSTEM_PROMPT,
            )
        )
        text = "".join(parts)
        if not text.strip():
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        return {**state, "answer": text, "used_mock": False, "citations": []}

    return answer


def make_answer_clarify(credentials: ProviderCredentials | None):
    def answer(state: AgentState) -> AgentState:
        query = state.get("collected") or state.get("query") or ""
        mock = _mock_clarify(query)
        if credentials is None:
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        parts = list(
            complete_text_stream(
                prompt=build_clarify_user_prompt(query=query),
                credentials=credentials,
                system=CLARIFY_SYSTEM_PROMPT,
            )
        )
        text = "".join(parts)
        if not text.strip():
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        return {**state, "answer": text, "used_mock": False, "citations": []}

    return answer


def make_answer_out_of_scope(credentials: ProviderCredentials | None):
    def answer(state: AgentState) -> AgentState:
        query = state.get("collected") or state.get("query") or ""
        mock = _mock_out_of_scope(query)
        if credentials is None:
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        parts = list(
            complete_text_stream(
                prompt=build_out_of_scope_user_prompt(query=query),
                credentials=credentials,
                system=OUT_OF_SCOPE_SYSTEM_PROMPT,
            )
        )
        text = "".join(parts)
        if not text.strip():
            return {**state, "answer": mock, "used_mock": True, "citations": []}
        return {**state, "answer": text, "used_mock": False, "citations": []}

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


def build_graph(
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
    top_k: int = DEFAULT_RETRIEVE_TOP_K,
):
    retriever = retriever or FakeRetriever()

    def intent_node(state: AgentState) -> AgentState:
        return classify_intent(state, credentials=credentials)

    def rewrite_node(state: AgentState) -> AgentState:
        return rewrite_issue(state, credentials=credentials)

    g = StateGraph(AgentState)
    g.add_node("classify_intent", intent_node)
    g.add_node("classify", classify)
    g.add_node("collect", collect)
    g.add_node("rewrite_issue", rewrite_node)
    g.add_node("retrieve", make_retrieve(retriever, top_k=top_k))
    g.add_node("answer", make_answer(credentials))
    g.add_node("answer_chitchat", make_answer_chitchat(credentials))
    g.add_node("answer_clarify", make_answer_clarify(credentials))
    g.add_node("answer_out_of_scope", make_answer_out_of_scope(credentials))
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
    g.add_edge("collect", "rewrite_issue")
    g.add_edge("rewrite_issue", "retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", "guardrail")
    g.add_edge("answer_chitchat", "guardrail")
    g.add_edge("answer_clarify", "guardrail")
    g.add_edge("answer_out_of_scope", "guardrail")
    g.add_edge("guardrail", END)
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


def run_agent_stream(
    query: str,
    request_id: str,
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
    top_k: int = DEFAULT_RETRIEVE_TOP_K,
    *,
    mock_sleep: float | None = MOCK_CHUNK_SLEEP_S,
) -> Iterator[ChatEvent | AgentState]:
    """Intent-route first; legal path rewrites, retrieves, then streams."""
    if any(k in query for k in GUARDRAIL_KEYWORDS):
        yield ChatEvent.error(request_id, "guardrail_blocked", "该问题触及安全策略，无法提供协助。")
        yield AgentState(
            query=query,
            request_id=request_id,
            blocked=True,
            block_reason="该问题触及安全策略，无法提供协助。",
            answer="",
            citations=[],
        )
        return

    retriever = retriever or FakeRetriever()
    state: AgentState = {
        "query": query,
        "request_id": request_id,
        "citations": [],
        "answer": "",
    }
    state = classify_intent(state, credentials=credentials)
    intent = state.get("intent") or "legal"

    if intent in ("chitchat", "ambiguous", "out_of_scope"):
        state = {**state, "collected": query.strip(), "citations": []}
        if intent == "chitchat":
            system = CHITCHAT_SYSTEM_PROMPT
            prompt = build_chitchat_user_prompt(query=query.strip())
            mock_text = _mock_chitchat(query.strip())
        elif intent == "out_of_scope":
            system = OUT_OF_SCOPE_SYSTEM_PROMPT
            prompt = build_out_of_scope_user_prompt(query=query.strip())
            mock_text = _mock_out_of_scope(query.strip())
        else:
            system = CLARIFY_SYSTEM_PROMPT
            prompt = build_clarify_user_prompt(query=query.strip())
            mock_text = _mock_clarify(query.strip())

        full = ""
        used_mock = False
        for item in _stream_answer_tokens(
            request_id=request_id,
            state=state,
            credentials=credentials,
            system=system,
            prompt=prompt,
            mock_text=mock_text,
            mock_sleep=mock_sleep,
        ):
            if isinstance(item, tuple):
                full, used_mock = item
            else:
                yield item

        final: AgentState = {
            **state,
            "answer": full,
            "used_mock": used_mock,
            "blocked": False,
            "block_reason": "",
            "citations": [],
        }
        yield final
        return

    state = classify(state)
    state = collect(state)
    state = rewrite_issue(state, credentials=credentials)
    state = make_retrieve(retriever, top_k=top_k)(state)

    citations = state.get("citations") or []
    for c in citations:
        yield ChatEvent.citation(request_id, Citation.model_validate(c))

    prompt = build_answer_user_prompt(
        query=state.get("collected") or query,
        case_type=state.get("case_type") or "general",
        citations=citations,
        user_issue_plain=state.get("user_issue_plain"),
        search_query=state.get("search_query"),
    )
    mock_text = _mock_answer(state)

    full = ""
    used_mock = False
    for item in _stream_answer_tokens(
        request_id=request_id,
        state=state,
        credentials=credentials,
        system=ANSWER_SYSTEM_PROMPT,
        prompt=prompt,
        mock_text=mock_text,
        mock_sleep=mock_sleep,
    ):
        if isinstance(item, tuple):
            full, used_mock = item
        else:
            yield item

    final_legal: AgentState = {
        **state,
        "answer": full,
        "used_mock": used_mock,
        "blocked": False,
        "block_reason": "",
    }
    yield final_legal
