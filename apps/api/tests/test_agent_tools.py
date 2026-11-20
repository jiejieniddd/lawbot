from __future__ import annotations

from uuid import uuid4

from lawbot.agent.citations import format_basis_line, repair_citations, status_label
from lawbot.agent.graph import run_agent_stream
from lawbot.agent.self_check import run_self_check
from lawbot.agent.tools import ToolContext, execute_legal_turn, execute_tool
from lawbot.domain.schemas import LEGAL_DISCLAIMER, ChatEvent, Citation
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.fake import FakeRetriever


class _BoomRetriever:
    def retrieve(self, query: str, top_k: int = 3):
        raise AssertionError(f"retrieve should not run for {query}")


def test_missing_tool_args_are_rejected(monkeypatch):
    formatted = {"n": 0}

    def _forbid_format(*args, **kwargs):
        formatted["n"] += 1
        raise AssertionError("formatter should not run")

    monkeypatch.setattr("lawbot.agent.tools.format_legal_report", _forbid_format)
    ctx = ToolContext(retriever=_BoomRetriever())

    missing_query = execute_tool("search_laws", {"top_k": 3}, ctx)
    bad_top_k = execute_tool("search_laws", {"query": "拖欠工资", "top_k": 0}, ctx)
    empty_facts = execute_tool(
        "ask_clarification",
        {"missing_facts": [], "question": "请补充：当事人"},
        ctx,
    )
    blank_basis = execute_tool(
        "emit_legal_report",
        {"legal_basis": "", "analysis": "分析", "advice": "建议", "risk": "风险"},
        ctx,
    )

    assert missing_query.ok is False
    assert bad_top_k.ok is False
    assert empty_facts.ok is False
    assert blank_basis.ok is False
    assert formatted["n"] == 0
    assert [item["ok"] for item in ctx.tool_trace] == [False, False, False, False]
    assert {item["name"] for item in ctx.tool_trace} == {
        "search_laws",
        "ask_clarification",
        "emit_legal_report",
    }


def test_clarification_and_search_are_mutually_exclusive():
    ctx = ToolContext(retriever=_BoomRetriever())
    outcomes = execute_legal_turn(
        [
            (
                "ask_clarification",
                {"missing_facts": ["当事人"], "question": "请补充：当事人"},
            ),
            ("search_laws", {"query": "拖欠工资", "top_k": 3}),
        ],
        ctx,
    )
    assert outcomes == []
    assert [item["name"] for item in ctx.tool_trace] == ["ask_clarification", "search_laws"]
    assert all(item["ok"] is False and item["error"] == "mutually_exclusive" for item in ctx.tool_trace)


def test_followup_turn_has_no_citations():
    events = list(
        run_agent_stream(
            "劳动合同纠纷咨询",
            "req-tool-followup",
            retriever=_BoomRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
    finals = [event for event in events if not isinstance(event, ChatEvent)]
    trace = finals[-1]["tool_trace"]
    assert citations == []
    assert "请补充：" in finals[-1]["answer"]
    assert [item["name"] for item in trace] == ["ask_clarification"]
    assert trace[0]["ok"] is True


def test_report_contains_four_headings_and_shared_disclaimer():
    events = list(
        run_agent_stream(
            "公司拖欠工资能否离职",
            "req-tool-report",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    tokens = [event for event in events if isinstance(event, ChatEvent) and event.type == "token"]
    citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
    answer = "".join(event.data["text"] for event in tokens)
    done = ChatEvent.done("req-tool-report", message_id=uuid4(), conversation_id=uuid4())
    for title in ("## 法律依据", "## 分析", "## 建议", "## 风险提示"):
        assert title in answer
    assert LEGAL_DISCLAIMER in answer
    assert done.data["disclaimer"] == LEGAL_DISCLAIMER
    assert citations
    assert citations[0].data.get("status") == "有效"
    assert citations[0].data.get("effective_date")
    assert citations[0].data.get("source_id")
    assert "现行有效" in answer
    assert "## 免责声明" in answer


def test_unsupported_article_is_marked_then_removed():
    hit = {
        "law_name": "中华人民共和国劳动合同法",
        "article_no": "第三十八条",
        "text": "用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
        "source_id": "fake-labor-38",
        "effective_date": "2008-01-01",
        "status": "有效",
        "score": 1.0,
    }
    fake = {
        "law_name": "中华人民共和国劳动合同法",
        "article_no": "第九十九条",
        "text": "",
        "source_id": "made-up",
        "status": "有效",
    }
    report = (
        "## 法律依据\n\n"
        f"{format_basis_line(hit)}\n"
        "《中华人民共和国劳动合同法》第九十九条\n\n"
        "## 分析\n\n可以依法处理。\n"
    )
    seen: dict[str, str] = {}

    def regenerate(marked: str, doubtful: list[tuple[str, str]], hits: list[dict]) -> str:
        assert any(article == "第九十九条" for _law, article in doubtful)
        assert "引用存疑" in marked
        seen["marked"] = marked
        return marked

    repaired = repair_citations(report, [hit, fake], [hit], regenerate)
    assert "第九十九条" not in repaired.text
    assert "引用存疑" not in repaired.text
    assert "第三十八条" in repaired.text
    assert "现行有效" in repaired.text
    assert "部分引用未通过核验，已省略" in repaired.text
    assert len(repaired.citations) == 1
    kept = repaired.citations[0]
    assert kept["article_no"] == "第三十八条"
    assert kept["effective_date"] == "2008-01-01"
    assert kept["status"] == "有效"
    assert kept["source_id"] == "fake-labor-38"
    assert seen["marked"]


def test_missing_status_is_not_guessed_valid():
    line = format_basis_line(
        {
            "law_name": "中华人民共和国劳动合同法",
            "article_no": "第三十八条",
            "text": "未及时足额支付劳动报酬的。",
            "source_id": "labor-38",
            "effective_date": "2008-01-01",
            "status": None,
        }
    )
    assert status_label(None) == "效力未标注"
    assert status_label("") == "效力未标注"
    assert "效力未标注" in line
    assert "现行有效" not in line
    assert "2008-01-01" in line
    assert "labor-38" in line


def test_named_missing_article_does_not_substitute_another():
    class OnlyThirtyEight:
        def retrieve(self, query: str, top_k: int = 3):
            return [
                RetrievedChunk(
                    citation=Citation(
                        law_name="中华人民共和国劳动合同法",
                        article_no="第三十八条",
                        text="未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
                        source_id="labor-38",
                        effective_date="2008-01-01",
                        status="有效",
                    ),
                    score=1.0,
                )
            ]

    events = list(
        run_agent_stream(
            "公司拖欠工资，想问《中华人民共和国劳动合同法》第九十九条还能不能用",
            "req-missing-article",
            retriever=OnlyThirtyEight(),
            credentials=None,
            mock_sleep=0,
        )
    )
    answer = "".join(
        event.data["text"] for event in events if isinstance(event, ChatEvent) and event.type == "token"
    )
    citations = [event for event in events if isinstance(event, ChatEvent) and event.type == "citation"]
    assert "未检索到明确依据" in answer
    assert "第三十八条" not in answer
    assert "第九十九条" not in answer
    assert citations == []


def test_absolute_promise_is_not_streamed_verbatim():
    hit = {
        "law_name": "中华人民共和国劳动合同法",
        "article_no": "第三十八条",
        "text": "用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
        "source_id": "fake-labor-38",
        "status": "有效",
    }
    draft = (
        "## 法律依据\n\n"
        f"{format_basis_line(hit)}\n\n"
        "## 分析\n\n你这边100%胜诉，可以解除劳动合同。\n\n"
        "## 建议\n\n保留工资证据。\n\n"
        "## 风险提示\n\n注意时效。\n\n"
        f"## 免责声明\n\n{LEGAL_DISCLAIMER}"
    )
    result = run_self_check(draft, [hit], [hit], credentials=None)
    assert "100%胜诉" not in result.text
    assert result.action in {"rewrite", "downgrade"}
    assert LEGAL_DISCLAIMER in result.text
    assert any(issue.startswith("absolute:") for issue in result.issues)


def test_unsupported_assertion_is_not_kept():
    hit = {
        "law_name": "中华人民共和国消费者权益保护法",
        "article_no": "第五十五条",
        "text": "经营者提供商品或者服务有欺诈行为的，应当增加赔偿。",
        "source_id": "consumer-55",
        "status": "有效",
    }
    draft = (
        "## 法律依据\n\n"
        f"{format_basis_line(hit)}\n\n"
        "## 分析\n\n可以解除劳动合同。\n\n"
        "## 建议\n\n先协商。\n\n"
        "## 风险提示\n\n注意证据。\n\n"
        f"## 免责声明\n\n{LEGAL_DISCLAIMER}"
    )
    result = run_self_check(draft, [hit], [hit], credentials=None)
    assert "可以解除劳动合同" not in result.text
    assert "检索结果未覆盖" in result.text or result.action == "downgrade"
    assert LEGAL_DISCLAIMER in result.text
    assert result.action in {"rewrite", "downgrade"}
    assert result.passed is False


def test_self_check_pass_keeps_report_structure():
    events = list(
        run_agent_stream(
            "公司拖欠工资能否离职",
            "req-self-check-pass",
            retriever=FakeRetriever(),
            credentials=None,
            mock_sleep=0,
        )
    )
    finals = [event for event in events if not isinstance(event, ChatEvent)]
    answer = finals[-1]["answer"]
    for title in ("## 法律依据", "## 分析", "## 建议", "## 风险提示"):
        assert title in answer
    assert LEGAL_DISCLAIMER in answer
    assert finals[-1]["self_check_action"] == "pass"
    assert finals[-1]["self_check_passed"] is True
