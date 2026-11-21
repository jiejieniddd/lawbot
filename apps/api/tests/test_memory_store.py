from __future__ import annotations

from lawbot.agent.memory_store import (
    InMemoryMemoryStore,
    memories_namespace,
    put_preference_memories,
    search_user_memories,
)
from lawbot.agent.prompts import assemble_answer_context, format_structured_slots


def test_inmemory_put_search_overlap():
    store = InMemoryMemoryStore()
    ns = memories_namespace("user-1")
    store.put(ns, "pref:province", {"text": "用户地区偏好：浙江", "type": "preference"})
    store.put(ns, "fact:1", {"text": "用户关心劳动报酬纠纷", "type": "case_fact"})
    hits = store.search(ns, query="浙江劳动", limit=5)
    assert hits
    texts = " ".join(h["text"] for h in hits)
    assert "浙江" in texts or "劳动" in texts


def test_put_preference_and_search_helpers():
    store = InMemoryMemoryStore()
    put_preference_memories(store, user_id="u2", province="上海", case_domain="labor")
    hits = search_user_memories(store, user_id="u2", query="上海欠薪", limit=4)
    assert any("上海" in (h.get("text") or "") for h in hits)


def test_assemble_keeps_slots_when_trimming():
    history = [{"role": "user", "content": f"旧消息{i}"} for i in range(20)]
    store = [{"text": f"记忆{i}", "type": "case_fact", "score": float(i)} for i in range(10)]
    body = assemble_answer_context(
        query="公司拖欠工资怎么办",
        case_type="labor",
        citations=[],
        task_goal="讨要工资",
        hard_constraints=["province=上海", "case_type=labor"],
        open_questions=[],
        key_entities=["公司"],
        confirmed_facts=["当事人", "争议事实"],
        memory_summary="已确认：当事人、争议事实",
        history=history,
        store_facts=store,
        max_recent_turns=6,
        char_budget=200,
    )
    assert "结构化槽位·不可裁剪" in body
    assert "讨要工资" in body
    assert "当事人" in body
    slots = format_structured_slots(
        task_goal="讨要工资",
        hard_constraints=["case_type=labor"],
        confirmed_facts=["当事人"],
    )
    assert "讨要工资" in slots
