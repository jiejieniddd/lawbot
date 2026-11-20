from __future__ import annotations

import re
from types import SimpleNamespace

from lawbot.agent.graph import classify_intent, run_agent_stream
from lawbot.domain.schemas import ChatEvent, Citation
from lawbot.llm.client import ProviderCredentials
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.fake import FakeRetriever


def test_mock_stream_emits_multiple_tokens_and_citations_first():
    events = list(
        run_agent_stream(
            "用人单位拖欠工资，劳动者能否解除劳动合同",
            "req-mock",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    tokens = [e for e in chat_events if e.type == "token"]
    citations = [e for e in chat_events if e.type == "citation"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]

    assert len(tokens) >= 2
    assert citations  # FakeRetriever returns hits for labor-ish queries
    # citations before first token
    first_token_idx = next(i for i, e in enumerate(chat_events) if e.type == "token")
    assert all(e.type == "citation" for e in chat_events[:first_token_idx])

    joined = "".join(e.data["text"] for e in tokens)
    assert finals
    assert finals[-1].get("answer") == joined
    assert finals[-1].get("used_mock") is True
    assert finals[-1].get("intent") == "legal"
    assert "## 法律依据" in joined
    assert "## 分析" in joined
    assert "## 建议" in joined
    assert "## 风险提示" in joined


def test_chitchat_skips_retrieve_and_legal_template():
    for q in ("你好", "谢谢"):
        events = list(
            run_agent_stream(
                q,
                f"req-chat-{q}",
                retriever=FakeRetriever(),
                credentials=None,
                mock_sleep=0,
            )
        )
        chat_events = [e for e in events if isinstance(e, ChatEvent)]
        citations = [e for e in chat_events if e.type == "citation"]
        tokens = [e for e in chat_events if e.type == "token"]
        finals = [e for e in events if not isinstance(e, ChatEvent)]

        assert citations == []
        assert tokens
        joined = "".join(e.data["text"] for e in tokens)
        assert "## 简单说" not in joined
        assert "## 法律上大概怎么看" not in joined
        assert "LawBot" in joined
        assert finals[-1].get("intent") == "chitchat"
        assert finals[-1].get("citations") == []


def test_legal_wage_query_still_uses_rag_template():
    events = list(
        run_agent_stream(
            "公司拖欠工资能否离职",
            "req-legal-wage",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    citations = [e for e in chat_events if e.type == "citation"]
    tokens = [e for e in chat_events if e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]

    assert citations
    joined = "".join(e.data["text"] for e in tokens)
    assert "## 法律依据" in joined
    assert "## 分析" in joined
    assert "## 建议" in joined
    assert "## 风险提示" in joined
    assert finals[-1].get("intent") == "legal"


def test_oral_hurt_extort_is_legal_consult():
    events = list(
        run_agent_stream(
            "我被人打了怎么讹他",
            "req-oral-hurt",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    tokens = [e for e in chat_events if e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)

    assert finals[-1].get("intent") == "legal"
    assert any(k in joined for k in ("报警", "赔偿", "伤害", "伤"))
    assert "法律问题领域" not in joined
    assert "法律问题类型" not in joined
    assert "哪类法律" not in joined
    assert finals[-1].get("search_query")


def test_classify_intent_rules():
    assert classify_intent({"query": "你好"})["intent"] == "chitchat"
    assert classify_intent({"query": "谢谢"})["intent"] == "chitchat"
    assert classify_intent({"query": "你能做什么"})["intent"] == "chitchat"
    assert classify_intent({"query": "公司拖欠工资能否离职"})["intent"] == "legal"
    assert classify_intent({"query": "公司拖欠工资怎么办"})["intent"] == "legal"
    assert classify_intent({"query": "我被人打了怎么讹他"})["intent"] == "legal"
    assert classify_intent({"query": "帮我写个排序算法"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "帮我写代码"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "红烧肉怎么做"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "嗯？"})["intent"] == "chitchat"
    assert classify_intent({"query": "想问点事"})["intent"] == "ambiguous"


def test_out_of_scope_skips_retrieve_and_legal_template():
    for q in ("帮我写个排序算法", "红烧肉怎么做"):
        events = list(
            run_agent_stream(
                q,
                f"req-oos-{q[:8]}",
                retriever=FakeRetriever(),
                credentials=None,
                mock_sleep=0,
            )
        )
        chat_events = [e for e in events if isinstance(e, ChatEvent)]
        citations = [e for e in chat_events if e.type == "citation"]
        tokens = [e for e in chat_events if e.type == "token"]
        finals = [e for e in events if not isinstance(e, ChatEvent)]

        assert citations == []
        assert tokens
        joined = "".join(e.data["text"] for e in tokens)
        assert "## 简单说" not in joined
        assert "## 法律上大概怎么看" not in joined
        assert "法律咨询" in joined
        assert finals[-1].get("intent") == "out_of_scope"
        assert finals[-1].get("citations") == []


def test_capability_question_is_chitchat():
    events = list(
        run_agent_stream(
            "你能做什么",
            "req-capability",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    citations = [e for e in chat_events if e.type == "citation"]
    tokens = [e for e in chat_events if e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]

    assert citations == []
    joined = "".join(e.data["text"] for e in tokens)
    assert "## 简单说" not in joined
    assert "法律" in joined
    assert finals[-1].get("intent") == "chitchat"


def test_llm_stream_token_order(monkeypatch):
    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        if "legal_basis" in (prompt or ""):
            return (
                '{"legal_basis":"《劳动合同法》第三十八条：未及时足额支付劳动报酬的。",'
                '"analysis":"拖欠工资时可以依法解除。",'
                '"advice":"保留工资证据并申请劳动仲裁。",'
                '"risk":"注意仲裁时效。"}'
            )
        return '{"search_query":"劳动报酬 解除劳动合同","user_issue_plain":"公司拖欠工资，想离职维权"}'

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "用人单位拖欠工资，劳动者能否解除劳动合同",
            "req-llm",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert finals[-1]["answer"] == joined
    assert "## 法律依据" in joined
    assert "## 分析" in joined
    assert "## 建议" in joined
    assert "## 风险提示" in joined
    assert finals[-1]["used_mock"] is False
    assert finals[-1]["intent"] == "legal"


def test_llm_stream_empty_falls_back_to_soft_fail(monkeypatch):
    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield  # make this a generator

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text",
        lambda **kwargs: '{"search_query":"劳动报酬 解除劳动合同","user_issue_plain":"公司拖欠工资，想离职维权"}',
    )

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "用人单位拖欠工资，劳动者能否解除劳动合同",
            "req-fallback",
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert len(tokens) >= 1
    assert finals[-1]["used_mock"] is True
    assert "模型暂时无法" in finals[-1]["answer"] or "稍后重试" in finals[-1]["answer"]
    assert "转账" not in finals[-1]["answer"]
    assert finals[-1]["intent"] == "legal"


def test_empty_cites_with_credentials_streams_llm_not_contract_mock(monkeypatch):
    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        if "legal_basis" in (prompt or ""):
            assert "（无）" in prompt or "未检索到" in prompt
            return (
                '{"legal_basis":"未检索到明确依据。不能据此引用具体法条。",'
                '"analysis":"就追尾事故，现有材料还对不上明确条文。",'
                '"advice":"建议先报警并固定证据。",'
                '"risk":"不要编造法条。"}'
            )
        return '{"search_query":"交通事故 人身损害 赔偿","user_issue_plain":"追尾想了解责任"}'

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)

    class EmptyRetriever:
        def retrieve(self, query: str, top_k: int = 3):
            return []

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "开车追尾了怎么办",
            "req-empty-cites-llm",
            retriever=EmptyRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert citations == []
    assert "报警" in joined or "追尾" in joined
    assert "转账" not in joined
    assert finals[-1]["used_mock"] is False
    assert finals[-1]["intent"] == "legal"


class _BoomRetriever:
    def retrieve(self, query: str, top_k: int = 3):
        raise AssertionError(f"retrieve should not run for {query}")


def _final(events):
    finals = [event for event in events if not isinstance(event, ChatEvent)]
    return finals[-1]


def test_missing_facts_only_follow_up():
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-missing",
            retriever=_BoomRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
    answer = _final(events)["answer"]
    assert citations == []
    assert "请补充：" in answer
    assert "当事人" in answer
    assert "争议事实" in answer
    assert "## 简单说" not in answer
    assert not re.search(r"第.+条", answer)


def test_followup_cap_returns_staged_conclusion():
    history = [
        {"role": "user", "content": "劳动合同纠纷咨询"},
        {"role": "assistant", "content": "请补充：当事人、争议事实。"},
        {"role": "user", "content": "还是想咨询劳动合同"},
        {"role": "assistant", "content": "请补充：当事人、争议事实。先说单位。"},
    ]
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-staged",
            retriever=_BoomRetriever(),
            credentials=None,
            mock_sleep=0,
            history=history,
        )
    )
    citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
    answer = _final(events)["answer"]
    assert citations == []
    assert "信息不足，建议补充" in answer
    assert "当事人" in answer
    assert "争议事实" in answer
    assert "## 简单说" not in answer
    assert not re.search(r"第.+条", answer)


def test_low_score_or_empty_retrieval_does_not_invent_articles():
    class EmptyRetriever:
        def retrieve(self, query: str, top_k: int = 3):
            return []

    class LowScoreRetriever:
        def retrieve(self, query: str, top_k: int = 3):
            return [
                RetrievedChunk(
                    citation=Citation(
                        law_name="中华人民共和国劳动合同法",
                        article_no="第三十八条",
                        text="未及时足额支付劳动报酬的。",
                        source_id="low-score",
                    ),
                    score=0.1,
                )
            ]

    for retriever, request_id in (
        (EmptyRetriever(), "req-empty-hits"),
        (LowScoreRetriever(), "req-low-score"),
    ):
        events = list(
            run_agent_stream(
                "公司拖欠工资能否离职",
                request_id,
                retriever=retriever,
                credentials=None,
                mock_sleep=0,
            )
        )
        citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
        answer = _final(events)["answer"]
        assert citations == []
        assert "未检索到明确依据" in answer
        assert "第三十八条" not in answer
        assert not re.search(r"第.+条", answer)


def test_second_turn_sees_followup_then_retrieves():
    first = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-round1",
            retriever=_BoomRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    ask = _final(first)["answer"]
    assert "请补充：" in ask
    second = list(
        run_agent_stream(
            "公司拖欠了三个月工资",
            "req-round2",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            history=[
                {"role": "user", "content": "劳动合同纠纷咨询"},
                {"role": "assistant", "content": ask},
            ],
        )
    )
    citations = [event for event in second if isinstance(event, ChatEvent) and event.type == "citation"]
    final = _final(second)
    # History still seeds follow-up count / slots when no checkpoint thread is used.
    assert int(final.get("followup_rounds") or 0) >= 1
    assert final.get("memory_summary")
    assert "已确认" in final["memory_summary"]
    assert citations
    assert final["intent"] == "legal"
