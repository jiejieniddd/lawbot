from __future__ import annotations

from types import SimpleNamespace

from lawbot.agent.graph import classify_intent, run_agent_stream
from lawbot.domain.schemas import ChatEvent
from lawbot.llm.client import ProviderCredentials
from lawbot.rag.fake import FakeRetriever


def test_mock_stream_emits_multiple_tokens_and_citations_first():
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
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
    assert "## 简单说" in joined


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
    assert "## 简单说" in joined
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
    def fake_stream(*, prompt: str, credentials, system: str | None = None):
        yield "你"
        yield "好"

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-llm",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert [e.data["text"] for e in tokens] == ["你", "好"]
    assert finals[-1]["answer"] == "你好"
    assert finals[-1]["used_mock"] is False
    assert finals[-1]["intent"] == "legal"


def test_llm_stream_empty_falls_back_to_soft_fail(monkeypatch):
    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield  # make this a generator

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
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
    def fake_stream(*, prompt: str, credentials, system: str | None = None):
        assert "（无）" in prompt or "未检索到" in prompt
        yield "就追尾事故，建议先报警并固定证据。"

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text",
        lambda **kwargs: '{"search_query":"交通事故 人身损害 赔偿","user_issue_plain":"追尾想了解责任"}',
    )

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
