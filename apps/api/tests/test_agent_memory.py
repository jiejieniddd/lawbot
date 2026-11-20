from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from lawbot.agent.graph import run_agent_stream
from lawbot.agent.preferences import LOCAL_LAW_NOTE, extract_province
from lawbot.domain.schemas import ChatEvent
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
