"""CareerBot latency regressions, entirely offline."""
import io
import logging
from types import SimpleNamespace

import pytest

from lawbot.agent import graph
from lawbot.domain.schemas import ChatEvent
from lawbot.llm import client as llm
from lawbot.rag.fake import FakeRetriever


@pytest.fixture
def creds():
    return llm.ProviderCredentials(SimpleNamespace(name="test", provider="openai"), "secret-key", "offline", None)


def forbidden(**kwargs):
    pytest.fail("unexpected model request")


@pytest.mark.parametrize("query,intent", [
    ("你好", "chitchat"), ("怎么做红烧肉", "out_of_scope"),
    ("帮我自动投递后端岗位", "out_of_scope"),
    ("Python 面试常考什么", "interview_qa"),
])
def test_known_intents_use_rules(monkeypatch, creds, query, intent):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    assert graph.classify_intent({"query": query}, creds)["intent"] == intent


def test_general_interview_no_auxiliary_calls(monkeypatch, creds):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    monkeypatch.setattr(graph, "complete_text_stream", lambda **kw: iter(["准备基础知识。", "再做练习。 "]))
    events = list(graph.run_agent_stream("Python 面试常考什么", "latency-test", credentials=creds, retriever=FakeRetriever(), mock_sleep=0))
    assert events[-1]["intent"] == "interview_qa"
    assert events[-1]["case_type"] == "general"
    assert any(isinstance(e, ChatEvent) and e.type == "token" for e in events)
    assert any(isinstance(e, ChatEvent) and e.type == "citation" for e in events)
    assert "self_check_action" in events[-1]


def test_ambiguous_intent_uses_bounded_model(monkeypatch, creds):
    seen = []
    def complete(**kw):
        seen.append(kw)
        return '{"intent":"out_of_scope"}'
    monkeypatch.setattr(graph, "complete_text", complete)
    assert graph.classify_intent({"query": "请解释一下光合作用"}, creds)["intent"] == "out_of_scope"
    assert len(seen) == 1
    assert seen[0]["timeout"] <= 8
    assert seen[0]["max_tokens"] == 256


def test_conflicting_track_still_uses_model(monkeypatch, creds):
    seen = []
    def complete(**kw):
        seen.append(kw)
        return '{"case_type":"frontend","confidence":0.9}'
    monkeypatch.setattr(graph, "complete_text", complete)
    out = graph.classify_case_type({"query": "后端与前端怎么选"}, creds)
    assert seen
    assert out["case_type_source"] == "llm"


def test_short_missing_slots_keep_followup(monkeypatch, creds):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    state = {"query": "想学", "case_type": "backend"}
    before = graph.make_collect(None)(state)
    after = graph.make_collect(creds)(state)
    assert before["missing_facts"] == after["missing_facts"]
    assert not after["facts_sufficient"]
    assert graph.route_facts(after) == "followup"


def test_context_supplement_preserved(monkeypatch, creds):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    state = {"query": "Redis", "case_type": "backend", "phase": "followup", "missing_facts": ["技术栈"], "confirmed_facts": ["意向方向"]}
    result = graph.make_collect(creds)(state)
    assert result["facts_sufficient"]
    assert "意向方向" in result["confirmed_facts"]


def test_known_long_question_skips_rewrite_model(monkeypatch, creds):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    query = "Python " + "我已经学习了一段时间，希望系统理解并给出例子。" * 5
    assert graph.rewrite_issue({"query": query}, creds)["rewrite_source"] == "passthrough"


@pytest.mark.parametrize("mode", ["empty", "error", "partial"])
def test_stream_failure_no_retry_or_duplicate(monkeypatch, creds, mode):
    monkeypatch.setattr(graph, "complete_text", forbidden)
    def stream(**kw):
        if mode == "partial":
            yield "已输出片段"
        if mode != "empty":
            raise TimeoutError("must not log prompt or secret-key")
    monkeypatch.setattr(graph, "complete_text_stream", stream)
    events = list(graph._stream_answer_tokens(request_id="test", state={"query": "后端面试"}, credentials=creds, system="", prompt="", mock_text="这是原先的备用模板", mock_sleep=0))
    body = "".join(e.data["text"] for e in events if isinstance(e, ChatEvent) and e.type == "token")
    assert events[-1][0] == body
    assert "原先的备用模板" not in body
    if mode == "partial":
        assert body.count("已输出片段") == 1
        assert "不完整" in body
    else:
        assert events[-1][2] is True
        assert "重试" in body or "抱歉" in body


def test_client_partial_failure_is_explicit(monkeypatch, creds, caplog):
    def stream(**kw):
        assert kw["num_retries"] == 0
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="part"), finish_reason=None)])
        raise RuntimeError("secret-key private question")
    monkeypatch.setattr("litellm.completion", stream)
    it = llm.complete_text_stream(prompt="private question", credentials=creds)
    assert next(it) == "part"
    with pytest.raises(llm.StreamTruncatedError):
        next(it)
    assert "secret-key" not in caplog.text
    assert "private question" not in caplog.text


@pytest.mark.parametrize("profile,limit", [("normal", 1600), ("compact", 800)])
def test_profile_preserves_default_and_compacts(monkeypatch, creds, profile, limit):
    monkeypatch.setenv("LLM_ANSWER_PROFILE", profile)
    monkeypatch.delenv("LLM_ANSWER_MAX_TOKENS", raising=False)
    seen = []
    def complete(**kw):
        seen.append(kw)
        return iter([])
    monkeypatch.setattr("litellm.completion", complete)
    list(llm.complete_text_stream(prompt="question", system="original", credentials=creds))
    assert seen[0]["max_tokens"] == limit
    system = seen[0]["messages"][0]["content"]
    assert (system == "original") == (profile == "normal")
    assert seen[0]["num_retries"] == 0


def test_timing_logger_visible_private_and_idempotent(monkeypatch, creds):
    from app.logging_config import configure_timing_logging
    configure_timing_logging()
    logger = logging.getLogger("lawbot.timing")
    count = len(logger.handlers)
    configure_timing_logging()
    assert len(logger.handlers) == count
    assert logger.isEnabledFor(logging.INFO)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger.addHandler(handler)
    try:
        monkeypatch.setattr(graph, "complete_text_stream", lambda **kw: iter(["回答"]))
        list(graph.run_agent_stream("Python 面试常考什么", "timing-check", credentials=creds, retriever=FakeRetriever(), mock_sleep=0))
    finally:
        logger.removeHandler(handler)
    text = output.getvalue()
    for stage in ("intent", "classification", "facts", "rewrite", "retrieval", "prepare_answer", "generation"):
        assert "stage=" + stage in text
    assert "request_id=timing-check" in text
    assert "Python 面试常考什么" not in text
    assert "secret-key" not in text


def test_http_first_token_includes_request_setup(client, otp_mail):
    from otp_helpers import register_user
    data = register_user(client, otp_mail, "latency@example.com")
    headers = {"Authorization": "Bearer " + data["access_token"], "X-Request-Id": "http-latency"}
    conv = client.post("/api/v1/conversations", headers=headers, json={}).json()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("lawbot.timing")
    logger.addHandler(handler)
    try:
        response = client.post("/api/v1/chat", headers=headers, json={"conversation_id": conv["id"], "content": "你好"})
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    logs = output.getvalue()
    for stage in ("request_setup", "first_token", "response_generation"):
        assert "request_id=http-latency stage=" + stage in logs
    assert "你好" not in logs
