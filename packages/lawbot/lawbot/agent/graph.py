from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from lawbot.domain.schemas import ChatEvent, Citation
from lawbot.llm.client import ProviderCredentials, complete_text
from lawbot.rag.base import Retriever
from lawbot.rag.fake import FakeRetriever

logger = logging.getLogger(__name__)

GUARDRAIL_KEYWORDS = ("如何制造炸弹", "洗钱方法", "伪造证件")


class AgentState(TypedDict, total=False):
    query: str
    request_id: str
    case_type: str
    collected: str
    citations: list[dict[str, Any]]
    answer: str
    blocked: bool
    block_reason: str
    used_mock: bool


def classify(state: AgentState) -> AgentState:
    q = state["query"]
    if any(k in q for k in ("劳动", "工资", "解雇")):
        case_type = "labor"
    elif any(k in q for k in ("合同", "违约")):
        case_type = "contract"
    else:
        case_type = "general"
    return {**state, "case_type": case_type}


def collect(state: AgentState) -> AgentState:
    return {**state, "collected": state["query"].strip()}


def make_retrieve(retriever: Retriever):
    def retrieve(state: AgentState) -> AgentState:
        chunks = retriever.retrieve(state["collected"], top_k=2)
        citations = [c.citation.model_dump() for c in chunks]
        return {**state, "citations": citations}

    return retrieve


def _mock_answer(state: AgentState) -> str:
    cites = state.get("citations") or []
    titles = "、".join(c.get("law_name", "") for c in cites) or "相关规定"
    return (
        f"根据您描述的「{state.get('case_type', 'general')}」类问题，"
        f"可参考{titles}。以下为基于检索结果的简要说明（模拟回复）："
        f"请结合具体事实咨询执业律师。"
    )


def make_answer(credentials: ProviderCredentials | None):
    def answer(state: AgentState) -> AgentState:
        mock = _mock_answer(state)
        if credentials is None:
            logger.info("LLM answer using mock stream (no enabled provider)")
            return {**state, "answer": mock, "used_mock": True}

        cites = state.get("citations") or []
        cite_block = "\n".join(
            f"- {c.get('law_name')} {c.get('article_no')}: {c.get('text')}" for c in cites
        )
        prompt = (
            f"用户问题：{state.get('collected') or state.get('query')}\n"
            f"案由类型：{state.get('case_type')}\n"
            f"检索条文：\n{cite_block or '（无）'}\n"
            "请用中文给出简要法律咨询参考，并声明不构成正式法律意见。"
        )
        text = complete_text(
            prompt=prompt,
            credentials=credentials,
            system="你是 LawBot 法律咨询助手。回答需谨慎、附免责声明。",
        )
        if not text.strip():
            logger.info("LiteLLM empty/failed; falling back to mock answer")
            return {**state, "answer": mock, "used_mock": True}
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


def build_graph(
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
):
    retriever = retriever or FakeRetriever()
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("collect", collect)
    g.add_node("retrieve", make_retrieve(retriever))
    g.add_node("answer", make_answer(credentials))
    g.add_node("guardrail", guardrail)
    g.set_entry_point("classify")
    g.add_edge("classify", "collect")
    g.add_edge("collect", "retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", "guardrail")
    g.add_edge("guardrail", END)
    return g.compile()


def run_agent_stream(
    query: str,
    request_id: str,
    retriever: Retriever | None = None,
    credentials: ProviderCredentials | None = None,
) -> Iterator[ChatEvent | AgentState]:
    """Run graph; yield ChatEvents for tokens/citations/errors, then final state."""
    graph = build_graph(retriever, credentials=credentials)
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

    final: AgentState = graph.invoke(
        {"query": query, "request_id": request_id, "citations": [], "answer": ""}
    )
    if final.get("blocked"):
        yield ChatEvent.error(
            request_id,
            "guardrail_blocked",
            final.get("block_reason") or "blocked",
        )
        yield final
        return

    answer_text = final.get("answer") or ""
    chunk_size = 8
    for i in range(0, len(answer_text), chunk_size):
        yield ChatEvent.token(request_id, answer_text[i : i + chunk_size])

    for c in final.get("citations") or []:
        yield ChatEvent.citation(request_id, Citation.model_validate(c))

    yield final
