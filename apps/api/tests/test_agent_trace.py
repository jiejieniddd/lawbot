from __future__ import annotations

import json
from pathlib import Path

from lawbot.agent.graph import run_agent_stream
from lawbot.agent.tracing import AgentTraceStore, AgentTracer, privacy_summary, redact_text
from lawbot.domain.schemas import ChatEvent
from lawbot.rag.fake import FakeRetriever


def _admin_headers(client):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_redact_strips_api_key_material():
    raw = "Bearer sk-abcdefghijklmnopqrstuvwxyz query=hello"
    cleaned = redact_text(raw)
    assert "sk-" not in cleaned
    assert "Bearer" not in cleaned or "[REDACTED]" in cleaned
    summary = privacy_summary("公司拖欠工资 sk-secretkey1234567890")
    assert "sk-secretkey" not in summary
    assert "hash=" in summary


def test_agent_stream_writes_jsonl_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path))
    request_id = "req-trace-wage-01"
    events = list(
        run_agent_stream(
            "公司拖欠工资能否离职",
            request_id,
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
            conversation_id="conv-trace-1",
        )
    )
    finals = [item for item in events if not isinstance(item, ChatEvent)]
    assert finals
    steps = AgentTraceStore(tmp_path).load(request_id)
    nodes = [step["node"] for step in steps]
    assert "classify_intent" in nodes
    assert "collect" in nodes
    assert "search_laws" in nodes
    assert "self_check" in nodes
    assert "final" in nodes
    search = next(step for step in steps if step["node"] == "search_laws")
    assert search["source_ids"]
    assert search["request_id"] == request_id
    assert search["conversation_id"] == "conv-trace-1"
    blob = json.dumps(steps, ensure_ascii=False)
    assert "sk-" not in blob


def test_followup_trace_marks_clarify(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path))
    request_id = "req-trace-clarify-01"
    list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            request_id,
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    steps = AgentTraceStore(tmp_path).load(request_id)
    nodes = [step["node"] for step in steps]
    assert "ask_clarification" in nodes
    ask = next(step for step in steps if step["node"] == "ask_clarification")
    assert ask["action"] == "clarify"
    final = next(step for step in steps if step["node"] == "final")
    assert "followup=True" in final["output_summary"]


def test_admin_can_read_trace(client, admin_user, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    assert get_settings().agent_trace_dir == str(tmp_path)
    store = AgentTraceStore(tmp_path)
    tracer = AgentTracer("req-admin-trace", conversation_id="c1", store=store)
    tracer.step(
        "search_laws",
        input_summary="q",
        output_summary="hits=1",
        source_ids=["fake-labor-38"],
    )
    tracer.step(
        "self_check",
        output_summary="ok",
        self_check_issues=[],
        action="pass",
    )
    headers = _admin_headers(client)
    resp = client.get("/api/admin/agent-traces/req-admin-trace", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["request_id"] == "req-admin-trace"
    assert len(body["steps"]) == 2
    assert body["steps"][0]["source_ids"] == ["fake-labor-38"]

    missing = client.get("/api/admin/agent-traces/does-not-exist", headers=headers)
    assert missing.status_code == 404
    get_settings.cache_clear()
