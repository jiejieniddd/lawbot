from __future__ import annotations

import json
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

from lawbot.agent.graph import classify_case_type, run_agent_stream
from lawbot.agent.preferences import LOCAL_LAW_NOTE, extract_province
from lawbot.domain.schemas import ChatEvent
from lawbot.llm.client import ProviderCredentials
from lawbot.rag.fake import FakeRetriever


def _final(events):
    finals = [item for item in events if not isinstance(item, ChatEvent)]
    return finals[-1]


def test_same_conversation_reads_prior_missing_facts():
    saver = MemorySaver()
    conv = "conv-memory-shared-1"
    first = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-mem-1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert first_state["phase"] == "followup"
    assert first_state.get("missing_facts")
    assert "请补充：" in first_state["answer"]
    prior_missing = list(first_state["missing_facts"])

    second = list(
        run_agent_stream(
            "公司拖欠了三个月工资",
            "req-mem-2",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    assert "当事人" in (second_state.get("confirmed_facts") or []) or "争议事实" in (
        second_state.get("confirmed_facts") or []
    )
    assert second_state.get("memory_summary")
    # First-round gaps should be reflected in summary / confirmed merge
    assert any(item in (second_state.get("memory_summary") or "") for item in ("已确认", "labor"))
    assert prior_missing  # recorded on turn 1
    assert second_state["phase"] == "analyze"
    citations = [e for e in second if isinstance(e, ChatEvent) and e.type == "citation"]
    assert citations


def test_new_conversation_does_not_leak_state():
    saver = MemorySaver()
    list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-mem-a1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id="conv-A",
            checkpointer=saver,
        )
    )
    fresh = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-mem-b1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id="conv-B",
            checkpointer=saver,
        )
    )
    state = _final(fresh)
    assert state["phase"] == "followup"
    assert state.get("followup_rounds") in {0, 1}
    # New thread should not already have labor slots confirmed from conv-A
    confirmed = state.get("confirmed_facts") or []
    assert "当事人" not in confirmed
    assert "争议事实" not in confirmed


def test_province_note_when_local_mentioned():
    assert extract_province("我在北京被公司拖欠工资") == "北京"
    events = list(
        run_agent_stream(
            "北京的公司拖欠工资两个月，能否解除劳动合同？",
            "req-mem-province",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            province_hint="北京",
        )
    )
    answer = _final(events)["answer"]
    assert LOCAL_LAW_NOTE in answer


class _CaptureRetriever:
    def __init__(self):
        self.queries: list[str] = []

    def retrieve(self, query: str, top_k: int = 3):
        self.queries.append(query)
        return FakeRetriever().retrieve(query, top_k=top_k)


def test_topic_switch_clears_tort_slots_and_search_query():
    saver = MemorySaver()
    conv = "conv-topic-switch-1"
    capturer = _CaptureRetriever()

    first = list(
        run_agent_stream(
            "开车追尾撞人受伤了怎么办",
            "req-topic-1",
            retriever=capturer,
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert "伤害或事故" in (first_state.get("confirmed_facts") or []) or first_state.get(
        "case_type"
    ) == "tort"

    second = list(
        run_agent_stream(
            "别人欠我钱不还这是怎么回事",
            "req-topic-2",
            retriever=capturer,
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    summary = second_state.get("memory_summary") or ""
    search = second_state.get("search_query") or ""
    confirmed = second_state.get("confirmed_facts") or []

    assert "伤害或事故" not in summary
    assert "伤害或事故" not in search
    assert "伤害或事故" not in confirmed
    assert "欠" in search or "钱" in search or "不还" in search
    # Last retrieve call should be about debt, not injury slots.
    assert capturer.queries
    last_q = capturer.queries[-1]
    assert "伤害或事故" not in last_q
    assert any(k in last_q for k in ("欠", "钱", "不还"))


def test_fallback_case_type_labor_not_tort_from_peichang():
    """「赔偿」 alone must not force tort;试用期辞退 → labor via rule (no LLM)."""
    out = classify_case_type(
        {"query": "试用期被辞退不给赔偿怎么办", "case_type": "contract", "confirmed_facts": []},
        credentials=None,
    )
    assert out["case_type"] == "labor"
    assert out["case_type_source"] == "rule"
    assert out["topic_shift"] is True


def test_topic_switch_debt_to_labor_no_injury_followup():
    """Same conversation: debt analysis then trial dismissal — never ask 伤害或事故."""
    saver = MemorySaver()
    conv = "conv-debt-to-labor-1"

    first = list(
        run_agent_stream(
            "别人欠我钱不还这是怎么回事",
            "req-debt-1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert first_state.get("case_type") in {"contract", "general"}

    second = list(
        run_agent_stream(
            "试用期被辞退不给赔偿怎么办",
            "req-labor-2",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    answer = second_state.get("answer") or ""
    summary = second_state.get("memory_summary") or ""
    missing = second_state.get("missing_facts") or []
    confirmed = second_state.get("confirmed_facts") or []

    assert second_state.get("case_type") == "labor"
    assert second_state.get("topic_shift") is True
    assert "伤害或事故" not in answer
    assert "伤害或事故" not in summary
    assert "伤害或事故" not in missing
    assert "伤害或事故" not in confirmed


def test_short_supplement_after_ask_merges_slots():
    """After 请补充, a short fact reply may merge checkpoint slots."""
    saver = MemorySaver()
    conv = "conv-labor-supplement-1"

    first = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-labor-ask",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert first_state["phase"] == "followup"
    assert "请补充：" in (first_state.get("answer") or "")

    second = list(
        run_agent_stream(
            "公司拖欠了三个月工资",
            "req-labor-patch",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    assert second_state.get("case_type") == "labor"
    confirmed = second_state.get("confirmed_facts") or []
    assert "当事人" in confirmed or "争议事实" in confirmed
    assert second_state["phase"] == "analyze"


def test_topic_switch_debt_to_company_no_loan_slot_followup():
    """After a full debt answer, one-person company/破产 must not ask借贷双槽."""
    saver = MemorySaver()
    conv = "conv-debt-to-company-1"

    first = list(
        run_agent_stream(
            "朋友借了我五万电话不接微信不回有借条起诉时效多久",
            "req-debt-full",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert first_state.get("phase") in {"analyze", "no_basis"}
    assert "请补充：合同或欠款关系" not in (first_state.get("answer") or "")

    second = list(
        run_agent_stream(
            "一人有限公司欠债借钱破产了老板是不是不用还",
            "req-company-debt",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    answer = second_state.get("answer") or ""
    missing = second_state.get("missing_facts") or []
    assert second_state.get("topic_shift") is True
    assert second_state.get("phase") in {"analyze", "no_basis"}
    assert "请补充：合同或欠款关系" not in answer
    assert "请补充：争议事实" not in answer
    assert "合同或欠款关系" not in missing
    assert "争议事实" not in "".join(str(m) for m in missing) or second_state.get(
        "facts_sufficient"
    )


def test_llm_case_type_classify_clears_on_topic_shift(monkeypatch):
    """Strong labor query uses rule case_type (skips 案由 LLM) and clears tort slots."""
    calls: list[str] = []

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        calls.append(system or "")
        if system and "案由" in system:
            return json.dumps(
                {
                    "case_type": "labor",
                    "topic_shift": True,
                    "confidence": 0.92,
                    "reason": "试用期辞退属劳动争议",
                },
                ensure_ascii=False,
            )
        if system and "意图" in system:
            return json.dumps({"intent": "legal", "reason": "有争议事实"}, ensure_ascii=False)
        if system and "改写" in system:
            return json.dumps(
                {"search_query": "试用期 解除 经济补偿", "user_issue_plain": "试用期被辞退"},
                ensure_ascii=False,
            )
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text_stream",
        lambda **_kwargs: iter(["## 简单说\n\n可依法主张权利。"]),
    )

    saver = MemorySaver()
    conv = "conv-llm-case-1"
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )

    list(
        run_agent_stream(
            "开车追尾撞人受伤了怎么办",
            "req-llm-tort",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )

    second = list(
        run_agent_stream(
            "试用期被辞退不给赔偿怎么办",
            "req-llm-labor",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    state = _final(second)
    assert state.get("case_type") == "labor"
    assert state.get("case_type_source") == "rule"
    assert state.get("topic_shift") is True
    assert "伤害或事故" not in (state.get("answer") or "")
    assert "伤害或事故" not in (state.get("missing_facts") or [])
    # Strong labor signal skips case_type classify LLM (facts prompt may still mention 案由).
    assert not any("案由与换题" in s for s in calls)


_SCREENSHOT_LABOR_Q = (
    "公司在员工试用期最后一天以不符合录用条件辞退且不给赔偿，合法吗？"
)


def test_screenshot_labor_query_no_injury_followup():
    """Screenshot-class labor question must not ask 伤害或事故."""
    events = list(
        run_agent_stream(
            _SCREENSHOT_LABOR_Q,
            "req-screenshot-labor",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id="conv-screenshot-labor-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    answer = state.get("answer") or ""
    assert state.get("case_type") == "labor"
    assert "请补充：伤害或事故" not in answer
    assert "伤害或事故" not in (state.get("missing_facts") or [])


def test_llm_tort_high_confidence_guarded_to_labor(monkeypatch):
    """Strong labor screenshot skips LLM; never tort followup."""

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        if system and "案由" in system:
            return json.dumps(
                {
                    "case_type": "tort",
                    "topic_shift": False,
                    "confidence": 0.95,
                    "reason": "提到赔偿误判侵权",
                },
                ensure_ascii=False,
            )
        if system and "意图" in system:
            return json.dumps({"intent": "legal", "reason": "有争议事实"}, ensure_ascii=False)
        if system and "改写" in system:
            return json.dumps(
                {
                    "search_query": "试用期 解除劳动合同 经济补偿",
                    "user_issue_plain": "试用期以不符合录用条件辞退",
                },
                ensure_ascii=False,
            )
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text_stream",
        lambda **_kwargs: iter(["## 简单说\n\n可依法主张权利。"]),
    )
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    out = classify_case_type(
        {"query": _SCREENSHOT_LABOR_Q, "case_type": "", "confirmed_facts": []},
        credentials=creds,
    )
    assert out["case_type"] == "labor"
    assert out["case_type_source"] == "rule"

    events = list(
        run_agent_stream(
            _SCREENSHOT_LABOR_Q,
            "req-guard-tort",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            conversation_id="conv-guard-tort-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    assert state.get("case_type") == "labor"
    assert "请补充：伤害或事故" not in (state.get("answer") or "")


def test_llm_labor_kept_without_guard(monkeypatch):
    """Strong labor query uses rule source (no case_type LLM)."""

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        if system and "案由" in system:
            return json.dumps(
                {
                    "case_type": "labor",
                    "topic_shift": False,
                    "confidence": 0.9,
                    "reason": "试用期辞退属劳动争议",
                },
                ensure_ascii=False,
            )
        return json.dumps({"intent": "legal", "reason": "ok"}, ensure_ascii=False)

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    out = classify_case_type(
        {"query": _SCREENSHOT_LABOR_Q, "case_type": "", "confirmed_facts": []},
        credentials=creds,
    )
    assert out["case_type"] == "labor"
    assert out["case_type_source"] == "rule"


def test_ambiguous_query_still_uses_case_type_llm(monkeypatch):
    """Weak/ambiguous legal query still calls case_type LLM when credentials present."""

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        if system and "案由" in system:
            return json.dumps(
                {
                    "case_type": "general",
                    "topic_shift": False,
                    "confidence": 0.55,
                    "reason": "表述笼统",
                },
                ensure_ascii=False,
            )
        return json.dumps({"intent": "legal", "reason": "ok"}, ensure_ascii=False)

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    out = classify_case_type(
        {"query": "这件事该怎么办比较好", "case_type": "", "confirmed_facts": []},
        credentials=creds,
    )
    assert out["case_type"] == "general"
    assert out["case_type_source"] == "llm"


def test_facts_llm_skipped_when_baseline_sufficient(monkeypatch):
    """Keyword slots already filled → facts sufficiency LLM not called."""
    systems: list[str] = []

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        systems.append(system or "")
        if system and ("事实充足" in system or "充足性" in system):
            raise AssertionError("facts sufficiency LLM must be skipped")
        if system and "案由" in system:
            return json.dumps(
                {
                    "case_type": "labor",
                    "topic_shift": False,
                    "confidence": 0.9,
                    "reason": "labor",
                },
                ensure_ascii=False,
            )
        if system and "意图" in system:
            return json.dumps({"intent": "legal", "reason": "ok"}, ensure_ascii=False)
        if system and "改写" in system:
            return json.dumps(
                {"search_query": "劳动 解除", "user_issue_plain": "辞退"},
                ensure_ascii=False,
            )
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text_stream",
        lambda **_kwargs: iter(["## 简单说\n\n可依法主张。"]),
    )
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "公司试用期辞退我不给赔偿怎么办",
            "req-facts-skip",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            conversation_id="conv-facts-skip-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    assert state.get("case_type") == "labor"
    assert state.get("facts_sufficient") is True
    assert state.get("facts_source") == "keyword"
    assert not any("事实充足" in s or "充足性" in s for s in systems)


def test_strong_labor_oral_zero_prestream_llm(monkeypatch):
    """「试用期被辞退」无「公司」：当事人槽命中，前置 complete_text 不含案由/事实充足。"""
    systems: list[str] = []

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        systems.append(system or "")
        if system and ("事实充足" in (system or "") or "充足性" in (system or "")):
            raise AssertionError("facts LLM must not run")
        if system and "案由与换题" in (system or ""):
            raise AssertionError("case_type LLM must not run")
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text_stream",
        lambda **_kwargs: iter(["## 简单说\n\n可依法主张。"]),
    )
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            "试用期被辞退不给赔偿怎么办",
            "req-prellm-zero",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            conversation_id="conv-prellm-zero-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    assert state.get("case_type") == "labor"
    assert state.get("case_type_source") == "rule"
    assert state.get("facts_sufficient") is True
    assert state.get("facts_source") == "keyword"
    assert state.get("rewrite_source") == "heuristic"
    assert "请补充：伤害或事故" not in (state.get("answer") or "")
    assert not any("案由与换题" in s for s in systems)
    assert not any("事实充足" in s or "充足性" in s for s in systems)


_SCREENSHOT_DEBT_Q = (
    "朋友借了我5万块钱，现在电话不接微信不回，借条还在。"
    "如果我起诉，诉讼时效是多久？过了时效钱还能要回来吗？"
)


def test_llm_facts_sufficient_debt_screenshot_no_dispute_followup(monkeypatch):
    """Full debt+维权 query: LLM facts sufficiency skips 请补充：争议事实."""

    def fake_complete(*, prompt: str, credentials, system: str | None = None):
        sys = system or ""
        # Check facts sufficiency before case_type (both prompts mention 案由).
        if "事实充足" in sys or "充足性" in sys:
            return json.dumps(
                {
                    "facts_sufficient": True,
                    "confirmed_facts": ["合同或欠款关系", "争议事实"],
                    "missing_facts": [],
                    "reason": "有借贷、失联、借条与起诉时效问题",
                },
                ensure_ascii=False,
            )
        if "案由与换题" in sys or ("案由" in sys and "充足" not in sys):
            return json.dumps(
                {
                    "case_type": "contract",
                    "topic_shift": False,
                    "confidence": 0.93,
                    "reason": "民间借贷催讨",
                },
                ensure_ascii=False,
            )
        if "意图" in sys:
            return json.dumps({"intent": "legal", "reason": "有争议事实"}, ensure_ascii=False)
        if "改写" in sys:
            return json.dumps(
                {
                    "search_query": "民间借贷 诉讼时效 借条",
                    "user_issue_plain": "朋友借五万元失联，有借条，问时效",
                },
                ensure_ascii=False,
            )
        return ""

    monkeypatch.setattr("lawbot.agent.graph.complete_text", fake_complete)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text_stream",
        lambda **_kwargs: iter(["## 简单说\n\n一般诉讼时效三年，可凭借条主张。"]),
    )
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    events = list(
        run_agent_stream(
            _SCREENSHOT_DEBT_Q,
            "req-debt-screenshot",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            conversation_id="conv-debt-screenshot-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    assert state.get("case_type") == "contract"
    assert state.get("case_type_source") == "rule"
    assert state.get("facts_sufficient") is True
    assert state.get("facts_source") == "keyword"
    assert "请补充：争议事实" not in (state.get("answer") or "")
    assert "争议事实" not in (state.get("missing_facts") or [])


def test_short_debt_query_still_followup_without_credentials():
    """Short contract ask without LLM still follow up for 争议事实."""
    from lawbot.agent.graph import collect

    # Keyword baseline: relation only, no dispute signal.
    slotted = collect(
        {"query": "别人欠钱", "case_type": "contract", "confirmed_facts": [], "followup_rounds": 0}
    )
    assert slotted.get("facts_sufficient") is False
    assert "争议事实" in (slotted.get("missing_facts") or [])

    events = list(
        run_agent_stream(
            "别人欠钱",
            "req-debt-short",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id="conv-debt-short-1",
            checkpointer=MemorySaver(),
        )
    )
    state = _final(events)
    assert state.get("case_type") == "contract"
    assert "请补充：争议事实" in (state.get("answer") or "")


def test_topic_switch_debt_to_one_person_company_clears_debt_slots():
    """借贷 → 一人公司：topic_shift，不再挡检索追问合同/欠款双槽."""
    saver = MemorySaver()
    conv = "conv-debt-to-company-1"
    list(
        run_agent_stream(
            "别人欠我钱不还这是怎么回事",
            "req-debt-co-1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    second = list(
        run_agent_stream(
            "一人公司的股东对公司债务要不要承担连带责任",
            "req-company-2",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    state = _final(second)
    answer = state.get("answer") or ""
    missing = state.get("missing_facts") or []
    assert state.get("topic_shift") is True
    assert "请补充：合同或欠款关系" not in answer
    assert "合同或欠款关系" not in missing
    assert "争议事实" not in missing or state.get("facts_sufficient") is True


def test_same_thread_slots_and_task_goal_persist():
    """Turn 2 with history=None still sees turn-1 confirmed via checkpoint + phase merge."""
    saver = MemorySaver()
    conv = "conv-slots-persist-1"
    first = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-slots-1",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
        )
    )
    first_state = _final(first)
    assert first_state.get("phase") == "followup"
    assert first_state.get("task_goal")
    assert first_state.get("open_questions")

    second = list(
        run_agent_stream(
            "公司拖欠了三个月工资",
            "req-slots-2",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id=conv,
            checkpointer=saver,
            history=None,
        )
    )
    second_state = _final(second)
    confirmed = second_state.get("confirmed_facts") or []
    assert "当事人" in confirmed or "争议事实" in confirmed
    assert second_state.get("task_goal")
    assert second_state.get("hard_constraints") is not None


def test_short_supplement_merges_without_history_when_phase_followup():
    """Checkpoint phase/missing enables allow_merge when chat passes history=None."""
    from lawbot.agent.graph import collect

    out = collect(
        {
            "query": "有借条微信不回",
            "case_type": "contract",
            "confirmed_facts": ["合同或欠款关系"],
            "missing_facts": ["争议事实"],
            "phase": "followup",
            "followup_rounds": 1,
            "topic_shift": False,
            "history": [],
        }
    )
    assert out.get("topic_shift") is False
    confirmed = out.get("confirmed_facts") or []
    assert "合同或欠款关系" in confirmed
    assert "争议事实" in confirmed or out.get("facts_sufficient") is True


def test_store_facts_injected_into_answer_prompt(monkeypatch):
    captured: list[str] = []

    def fake_stream(**kwargs):
        captured.append(kwargs.get("prompt") or "")
        yield "## 简单说\n可依法主张。"

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock", provider="openai"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    list(
        run_agent_stream(
            "公司拖欠工资怎么办",
            "req-store-inject",
            retriever=FakeRetriever(),
            credentials=creds,
            mock_sleep=0,
            store_facts=[{"text": "用户地区偏好：北京", "type": "preference", "score": 2.0}],
        )
    )
    assert captured
    assert "跨会话用户记忆" in captured[0] or "用户地区偏好：北京" in captured[0]
    assert "结构化槽位" in captured[0]
