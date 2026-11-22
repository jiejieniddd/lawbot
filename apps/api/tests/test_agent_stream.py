from __future__ import annotations

import re
from types import SimpleNamespace

from lawbot.agent.graph import classify_intent, run_agent_stream
from lawbot.domain.schemas import ChatEvent, Citation
from lawbot.llm.client import ProviderCredentials, StreamTruncatedError
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.fake import FakeRetriever


def test_mock_stream_emits_tokens_then_citations_on_success():
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
    statuses = [e for e in chat_events if e.type == "status"]
    assert statuses
    assert statuses[0].data.get("message") == "正在理解问题…"
    # Citations only after successful generation (tokens first).
    first_token_idx = next(i for i, e in enumerate(chat_events) if e.type == "token")
    first_cite_idx = next(i for i, e in enumerate(chat_events) if e.type == "citation")
    assert first_token_idx < first_cite_idx

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
    assert classify_intent({"query": "你好"})["intent_source"] == "rule"
    assert classify_intent({"query": "在吗"})["intent"] == "chitchat"
    assert classify_intent({"query": "在嘛"})["intent"] == "chitchat"
    assert classify_intent({"query": "谢谢"})["intent"] == "chitchat"
    assert classify_intent({"query": "你能做什么"})["intent"] == "chitchat"
    assert classify_intent({"query": "公司拖欠工资能否离职"})["intent"] == "legal"
    assert classify_intent({"query": "公司拖欠工资怎么办"})["intent"] == "legal"
    assert classify_intent({"query": "我被人打了怎么讹他"})["intent"] == "legal"
    assert classify_intent({"query": "帮我写个排序算法"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "帮我写代码"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "红烧肉怎么做"})["intent"] == "out_of_scope"
    assert classify_intent({"query": "嗯？"})["intent"] == "chitchat"
    assert classify_intent({"query": "？？"})["intent"] in {"chitchat", "ambiguous"}
    assert classify_intent({"query": "想问点事"})["intent"] == "ambiguous"


def test_chitchat_shortcircuit_skips_llm_and_retrieve(monkeypatch):
    def boom_complete(**_kwargs):
        raise AssertionError("chitchat short-circuit must not call complete_text")

    def boom_stream(**_kwargs):
        raise AssertionError("chitchat short-circuit must not call complete_text_stream")
        yield  # pragma: no cover

    monkeypatch.setattr("lawbot.agent.graph.complete_text", boom_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", boom_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    for q in ("你好", "在吗"):
        events = list(
            run_agent_stream(
                q,
                f"req-short-{q}",
                retriever=_BoomRetriever(),
                credentials=creds,
                mock_sleep=0,
            )
        )
        tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
        finals = [e for e in events if not isinstance(e, ChatEvent)]
        assert tokens
        joined = "".join(e.data["text"] for e in tokens)
        assert "LawBot" in joined
        assert finals[-1].get("intent") == "chitchat"
        assert finals[-1].get("used_mock") is True


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
    def boom_complete(**_kwargs):
        raise AssertionError("report complete_text should not run for streamed legal answer")

    def fake_stream(*, prompt: str, credentials, system: str | None = None):
        assert "拖欠" in prompt or "工资" in prompt
        yield "## 简单说\n\n"
        yield "可以依法解除。\n\n"
        yield "## 你可以怎么做\n\n保留证据并申请仲裁。"

    monkeypatch.setattr("lawbot.agent.graph.complete_text", boom_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)

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
    assert len(tokens) >= 2
    assert "依法解除" in joined
    # Final answer may apply rule self-check after stream (persistence).
    assert "依法解除" in (finals[-1]["answer"] or "")
    assert finals[-1]["used_mock"] is False
    assert finals[-1]["intent"] == "legal"


def test_stream_truncated_keeps_partial_and_footer(monkeypatch):
    def boom_complete(**_kwargs):
        raise AssertionError("truncated partial must not fall back to complete_text")

    def truncated_stream(*, prompt: str, credentials, system: str | None = None):
        yield "## 简单说\n\n已生成前半段。"
        raise StreamTruncatedError(kind="idle", chars_emitted=20, provider="mock")

    monkeypatch.setattr("lawbot.agent.graph.complete_text", boom_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", truncated_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "大三计算机想做后端，常见面试题怎么准备",
            "req-llm-trunc",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert "已生成前半段" in joined
    assert "可能不完整" in joined
    assert "篇幅受限" not in joined
    assert "流式中断，正在改用备用通道" not in "".join(
        str(e.data.get("message") or "") for e in events if isinstance(e, ChatEvent) and e.type == "status"
    )
    assert finals
    assert "已生成前半段" in (finals[-1].get("answer") or "")
    assert "可能不完整" in (finals[-1].get("answer") or "")
    assert finals[-1]["used_mock"] is False


def test_stream_length_truncated_keeps_partial_and_length_footer(monkeypatch):
    def boom_complete(**_kwargs):
        raise AssertionError("length-truncated partial must not fall back to complete_text")

    def length_stream(*, prompt: str, credentials, system: str | None = None):
        yield "## 简单说\n\n已生成前半段，停在半句「"
        raise StreamTruncatedError(kind="length", chars_emitted=30, provider="mock")

    monkeypatch.setattr("lawbot.agent.graph.complete_text", boom_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", length_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "大三计算机想做后端，常见面试题怎么准备",
            "req-llm-length",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert "已生成前半段" in joined
    assert "篇幅受限" in joined
    assert "追问补全" in joined
    assert "生成超时" not in joined
    assert finals
    assert "篇幅受限" in (finals[-1].get("answer") or "")
    assert "生成超时" not in (finals[-1].get("answer") or "")
    assert finals[-1]["used_mock"] is False


def test_stream_emits_status_before_answer():
    events = list(
        run_agent_stream(
            "你好",
            "req-status-first",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    assert chat_events
    assert chat_events[0].type == "status"
    assert "理解" in str(chat_events[0].data.get("message") or "")
    assert any(e.type == "token" for e in chat_events)
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert finals


def test_llm_timeout_degrades_without_hang(monkeypatch):
    def timeout_complete(**_kwargs):
        raise TimeoutError("Request timed out")

    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield

    monkeypatch.setattr("lawbot.agent.graph.complete_text", timeout_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "用人单位拖欠工资，劳动者能否解除劳动合同",
            "req-llm-timeout",
            credentials=creds,
            mock_sleep=0,
        )
    )
    chat_events = [e for e in events if isinstance(e, ChatEvent)]
    assert chat_events[0].type == "status"
    tokens = [e for e in chat_events if e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert tokens
    assert finals
    answer = finals[-1].get("answer") or ""
    assert answer.strip()
    # Heuristic/soft-fail path — not hung empty
    assert "转账" not in answer


class _DebtHitRetriever:
    """High-score debt-ish hit so analyze path runs; text matches 欠/钱 topic keys."""

    def retrieve(self, query: str, top_k: int = 3):
        return [
            RetrievedChunk(
                citation=Citation(
                    law_name="中华人民共和国民法典",
                    article_no="第六百七十五条",
                    text="借款人应当按照约定的期限返还借款。别人欠钱不还可依法请求返还。",
                    source_id="fake-debt-675",
                ),
                score=0.95,
            )
        ]


def test_llm_stream_empty_falls_back_to_complete_text(monkeypatch):
    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield  # make this a generator

    def fake_complete(**kwargs):
        system = kwargs.get("system") or ""
        prompt = kwargs.get("prompt") or ""
        if "search_query" in system or "改写" in system or "JSON" in system and "search_query" in prompt:
            return '{"search_query":"劳动报酬 解除劳动合同","user_issue_plain":"公司拖欠工资，想离职维权"}'
        if "legal_basis" in system or "legal_basis" in prompt:
            return ""
        # Answer-generation fallback after empty stream (align names with FakeRetriever)
        return (
            "## 法律依据\n\n"
            "依据《中华人民共和国劳动合同法》第三十八条："
            "用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。\n\n"
            "## 分析\n\n拖欠工资可依法解除。\n\n"
            "## 建议\n\n先书面催讨。\n\n"
            "## 风险提示\n\n注意时效。\n\n"
            "## 免责声明\n\n不构成正式法律意见。"
        )

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)
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
            "req-fallback-complete",
            credentials=creds,
            mock_sleep=0,
            retriever=FakeRetriever(),
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert len(tokens) >= 1
    assert finals[-1]["used_mock"] is False
    assert "拖欠工资" in finals[-1]["answer"] or "解除" in finals[-1]["answer"]
    assert "稍后重试" not in finals[-1]["answer"]
    assert "模型暂时无法" not in finals[-1]["answer"]
    assert finals[-1]["intent"] == "legal"
    assert citations  # successful generation keeps citations


def test_llm_stream_and_complete_empty_soft_fail_uses_raw_query(monkeypatch):
    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield

    def empty_or_rewrite(**kwargs):
        prompt = kwargs.get("prompt") or ""
        system = kwargs.get("system") or ""
        # Allow rewrite / short heuristic JSON; never return answer body.
        if "search_query" in prompt and "user_issue_plain" in (system + prompt):
            return '{"search_query":"劳动报酬","user_issue_plain":"拖欠工资"}'
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)
    monkeypatch.setattr("lawbot.agent.graph.complete_text", empty_or_rewrite)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    # Hit path so prepare stores soft-fail mock_text; both LLM paths empty → soft-fail.
    user_q = "别人欠我钱不还这是怎么回事"
    events = list(
        run_agent_stream(
            user_q,
            "req-soft-fail-raw",
            credentials=creds,
            mock_sleep=0,
            retriever=_DebtHitRetriever(),
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert tokens
    answer = finals[-1]["answer"]
    assert finals[-1]["used_mock"] is True
    assert "稍后重试" in answer or "抱歉" in answer
    assert "本轮问题" in answer
    assert "欠我钱" in answer
    assert "已确认：伤害" not in answer
    assert "伤害或事故" not in answer
    assert citations == []
    assert finals[-1].get("citations") == []


class _EmptyRetriever:
    def retrieve(self, query: str, top_k: int = 3):
        return []


def test_empty_cites_debt_streams_topic_llm(monkeypatch):
    def boom_complete(**_kwargs):
        raise AssertionError("no-basis stream should not call complete_text for report JSON")

    def fake_stream(*, prompt: str, credentials, system: str | None = None):
        assert "欠" in prompt or "钱" in prompt
        assert "未检索到" in (system or "") or "检索" in prompt
        yield (
            "## 法律依据\n\n未检索到明确依据。\n\n"
            "## 分析\n\n就别人欠钱不还，属于债权债务争议。\n\n"
            "## 建议\n\n可先书面催收并保留证据，必要时起诉或申请支付令。\n\n"
            "## 风险提示\n\n注意诉讼时效，不要采用违法手段追债。\n\n"
            "## 免责声明\n\n不构成正式法律意见。"
        )

    monkeypatch.setattr("lawbot.agent.graph.complete_text", boom_complete)
    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "别人欠我钱不还",
            "req-empty-debt",
            retriever=_EmptyRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert citations == []
    assert "未检索到" in joined
    assert any(k in joined for k in ("催收", "催告", "起诉", "支付令", "协商"))
    assert "伤情" not in joined
    assert finals[-1]["used_mock"] is False
    assert finals[-1].get("phase") == "no_basis"
    assert finals[-1].get("citations") == []


def test_empty_cites_extort_rejects_and_guides_legal(monkeypatch):
    def fake_stream(*, prompt: str, credentials, system: str | None = None):
        assert "讹" in prompt
        yield (
            "## 法律依据\n\n未检索到明确依据。\n\n"
            "## 分析\n\n开车被撞应走合法索赔，不能「讹一笔」。\n\n"
            "## 建议\n\n可报警、固定证据后协商或起诉请求赔偿，禁止敲诈勒索。\n\n"
            "## 风险提示\n\n违法取财可能担责。\n\n"
            "## 免责声明\n\n不构成正式法律意见。"
        )

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "开车被撞能不能讹一笔",
            "req-empty-extort",
            retriever=_EmptyRetriever(),
            credentials=creds,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    joined = "".join(e.data["text"] for e in tokens)
    assert "未检索到" in joined
    assert any(k in joined for k in ("敲诈", "讹", "合法索赔", "禁止"))
    assert "第三十八条" not in joined
    assert not re.search(r"第.+条", joined)
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    assert finals[-1].get("phase") == "no_basis"
    assert finals[-1].get("citations") == []


def test_empty_cites_without_credentials_heuristic_fallback():
    events = list(
        run_agent_stream(
            "别人欠我钱不还怎么办",
            "req-empty-no-creds",
            retriever=_EmptyRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    tokens = [e for e in events if isinstance(e, ChatEvent) and e.type == "token"]
    finals = [e for e in events if not isinstance(e, ChatEvent)]
    joined = "".join(e.data["text"] for e in tokens)
    assert tokens
    assert "未检索到" in joined
    assert "欠" in joined or "钱" in joined
    assert "伤情" not in joined
    assert finals[-1]["used_mock"] is True
    assert finals[-1].get("phase") == "no_basis"


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


class _WeakOffTopicRetriever:
    """Weak litigation hit with no debt topic keywords — should be filtered out."""

    def retrieve(self, query: str, top_k: int = 3):
        return [
            RetrievedChunk(
                citation=Citation(
                    law_name="中华人民共和国民事诉讼法",
                    article_no="第一百二十条",
                    text="起诉应当向人民法院递交起诉状，并按照被告人数提出副本。",
                    source_id="fake-proc-120",
                ),
                score=0.68,
            )
        ]


def test_weak_off_topic_hits_filtered_to_no_basis():
    events = list(
        run_agent_stream(
            "别人欠我钱不还",
            "req-weak-filter",
            retriever=_WeakOffTopicRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    final = _final(events)
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    assert final.get("retrieval_usable") is False
    assert citations == []
    assert final.get("citations") == []
    answer = final.get("answer") or ""
    assert "第一百二十条" not in answer
    assert "起诉状" not in answer


_PET_DRAFT_Q = "帮我写一份关于‘宠物狗继承主人遗产’的标准法律文书。"


def test_pet_inheritance_draft_is_out_of_scope_no_offtopic_cites():
    """代写文书不进检索；不得展示商品房/食品安全引用。"""
    events = list(
        run_agent_stream(
            _PET_DRAFT_Q,
            "req-pet-draft",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    final = _final(events)
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    answer = final.get("answer") or ""
    assert final.get("intent") == "out_of_scope"
    assert final.get("phase") == "out_of_scope"
    assert citations == []
    assert final.get("citations") == []
    assert "商品房" not in answer
    assert "食品安全" not in answer
    assert "代写" in answer or "文书" in answer
    assert "继承人" in answer or "宠物" in answer


class _HighScoreFoodHousingRetriever:
    """High BM25-like scores for food/housing — must not pass inheritance topic filter."""

    def retrieve(self, query: str, top_k: int = 3):
        return [
            RetrievedChunk(
                citation=Citation(
                    law_name="中华人民共和国食品安全法",
                    article_no="第一百二十三条",
                    text="违反本法规定，有下列情形之一，尚不构成犯罪的……",
                    source_id="fake-food-123",
                ),
                score=13.0,
            ),
            RetrievedChunk(
                citation=Citation(
                    law_name="最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释",
                    article_no="第十四条",
                    text="由于出卖人的原因，买受人未能取得不动产权属证书的……",
                    source_id="fake-house-14",
                ),
                score=13.0,
            ),
        ]


class _InheritanceOnTopicRetriever:
    def retrieve(self, query: str, top_k: int = 3):
        return [
            RetrievedChunk(
                citation=Citation(
                    law_name="中华人民共和国民法典",
                    article_no="第一千一百二十七条",
                    text="遗产按照下列顺序继承：……",
                    source_id="fake-inherit-1127",
                ),
                score=0.9,
            )
        ]


def test_high_score_food_housing_filtered_for_inheritance_query():
    events = list(
        run_agent_stream(
            "宠物狗能不能继承主人的遗产？",
            "req-inherit-filter",
            retriever=_HighScoreFoodHousingRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    final = _final(events)
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    answer = final.get("answer") or ""
    assert final.get("intent") == "legal"
    assert final.get("retrieval_usable") is False
    assert citations == []
    assert final.get("citations") == []
    assert "食品安全" not in answer
    assert "商品房" not in answer


def test_inheritance_on_topic_hit_kept():
    events = list(
        run_agent_stream(
            "遗产继承顺序是怎样的？",
            "req-inherit-keep",
            retriever=_InheritanceOnTopicRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    final = _final(events)
    citations = [e for e in events if isinstance(e, ChatEvent) and e.type == "citation"]
    assert final.get("retrieval_usable") is True
    assert citations
    joined = " ".join(
        f"{c.data.get('law_name') or ''} {c.data.get('text') or ''}" for c in citations
    )
    assert "继承" in joined or "遗产" in joined


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
