from __future__ import annotations

from types import SimpleNamespace

from lawbot.agent.graph import _mock_answer, make_answer
from lawbot.agent.prompts import (
    ANSWER_SYSTEM_PROMPT,
    CHITCHAT_SYSTEM_PROMPT,
    CLARIFY_SYSTEM_PROMPT,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    build_answer_user_prompt,
    build_chitchat_user_prompt,
    build_clarify_user_prompt,
    build_out_of_scope_user_prompt,
    format_citation_block,
)
from lawbot.llm.client import ProviderCredentials


def test_system_prompt_has_consultative_constraints():
    assert "禁止" in ANSWER_SYSTEM_PROMPT
    assert "法条汇编" in ANSWER_SYSTEM_PROMPT or "条文清单" in ANSWER_SYSTEM_PROMPT
    assert "## 简单说" in ANSWER_SYSTEM_PROMPT
    assert "## 你可以怎么做" in ANSWER_SYSTEM_PROMPT
    assert "Markdown" in ANSWER_SYSTEM_PROMPT
    assert "不得编造" in ANSWER_SYSTEM_PROMPT or "禁止捏造" in ANSWER_SYSTEM_PROMPT
    assert "未检索到直接依据" in ANSWER_SYSTEM_PROMPT
    assert "法律领域" in ANSWER_SYSTEM_PROMPT or "自报" in ANSWER_SYSTEM_PROMPT


def test_user_prompt_with_citations_and_empty():
    cites = [
        {
            "law_name": "劳动合同法",
            "article_no": "第三十八条",
            "text": "用人单位有下列情形之一的，劳动者可以解除劳动合同……",
            "source_id": "src-1",
        }
    ]
    with_cites = build_answer_user_prompt(
        query="公司拖欠工资能否解除劳动合同",
        case_type="labor",
        citations=cites,
        user_issue_plain="公司拖欠工资，想离职维权",
        search_query="劳动报酬 解除劳动合同",
    )
    assert "公司拖欠工资能否解除劳动合同" in with_cites
    assert "劳动合同法" in with_cites
    assert "第三十八条" in with_cites
    assert "src-1" in with_cites
    assert "## 简单说" in with_cites
    assert "禁止" in with_cites

    empty = build_answer_user_prompt(query="某某冷门问题", case_type="general", citations=[])
    assert "（无）" in empty or format_citation_block([]) == "（无）"
    assert "未检索到直接依据" in empty


def test_mock_answer_analytical_with_and_without_citations():
    empty_state = {
        "query": "偏门法规咨询",
        "collected": "偏门法规咨询",
        "case_type": "general",
        "citations": [],
        "intent": "legal",
    }
    empty_text = _mock_answer(empty_state)
    assert "未检索到直接依据" in empty_text or "未配置可用模型" in empty_text
    assert "合同、转账" not in empty_text
    assert "转账" not in empty_text

    with_cites = _mock_answer(
        {
            "query": "公司拖欠工资能否解除劳动合同",
            "collected": "公司拖欠工资能否解除劳动合同",
            "case_type": "labor",
            "intent": "legal",
            "citations": [
                {
                    "law_name": "劳动合同法",
                    "article_no": "第三十八条",
                    "text": "用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
                    "source_id": "src-1",
                }
            ],
        }
    )
    assert "## 你可以怎么做" in with_cites
    assert "劳动合同法" in with_cites
    assert "模拟回复" in with_cites
    assert "## 简单说" in with_cites


def test_make_answer_uses_new_prompts(monkeypatch):
    captured: dict[str, str] = {}

    def fake_complete_text_stream(*, prompt: str, credentials, system: str | None = None):
        captured["prompt"] = prompt
        captured["system"] = system or ""
        yield (
            "## 简单说\n\n可以依法解除。\n\n"
            "## 你可以怎么做\n\n……\n\n"
            "## 法律上大概怎么看\n\n- **《劳动合同法》第三十八条**：……\n\n"
            "## 注意\n\n……\n\n"
            "## 声明\n\n……"
        )

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_complete_text_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    node = make_answer(creds)
    out = node(
        {
            "query": "公司拖欠工资能否解除劳动合同",
            "collected": "公司拖欠工资能否解除劳动合同",
            "case_type": "labor",
            "citations": [
                {
                    "law_name": "劳动合同法",
                    "article_no": "第三十八条",
                    "text": "……",
                    "source_id": "s1",
                }
            ],
        }
    )
    assert out["used_mock"] is False
    assert "可以依法解除" in out["answer"]
    assert "法条汇编" in captured["system"] or "条文清单" in captured["system"]
    assert "Markdown" in captured["system"]
    assert "## 简单说" in captured["prompt"]
    assert "劳动合同法" in captured["prompt"]


def test_make_answer_without_credentials_uses_mock():
    node = make_answer(None)
    out = node(
        {
            "query": "测试",
            "collected": "测试",
            "case_type": "general",
            "citations": [],
            "intent": "legal",
        }
    )
    assert out["used_mock"] is True
    assert "未配置可用模型" in out["answer"] or "未检索到直接依据" in out["answer"]
    assert "合同、转账" not in out["answer"]
    assert "转账" not in out["answer"]


def test_make_answer_with_credentials_empty_cites_uses_llm(monkeypatch):
    called: dict[str, bool] = {"stream": False}

    def fake_complete_text_stream(*, prompt: str, credentials, system: str | None = None):
        called["stream"] = True
        assert "未检索到" in prompt or "（无）" in prompt
        yield "## 简单说\n\n就你说的追尾，先报警固定证据。\n\n"
        yield "## 你可以怎么做\n\n……"

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_complete_text_stream)

    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    node = make_answer(creds)
    out = node(
        {
            "query": "开车追尾了怎么办",
            "collected": "开车追尾了怎么办",
            "case_type": "tort",
            "citations": [],
            "intent": "legal",
            "user_issue_plain": "交通事故想了解责任",
            "search_query": "交通事故 人身损害 赔偿",
        }
    )
    assert called["stream"] is True
    assert out["used_mock"] is False
    assert "追尾" in out["answer"] or "报警" in out["answer"]
    assert "合同、转账" not in out["answer"]
    assert "转账" not in out["answer"]


def test_make_answer_stream_fail_soft_not_contract_mock(monkeypatch):
    def empty_stream(*, prompt: str, credentials, system: str | None = None):
        if False:  # pragma: no cover
            yield ""
        return
        yield

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    out = make_answer(creds)(
        {
            "query": "开车追尾了怎么办",
            "collected": "开车追尾了怎么办",
            "citations": [],
            "intent": "legal",
        }
    )
    assert out["used_mock"] is True
    assert "模型暂时无法" in out["answer"] or "稍后重试" in out["answer"]
    assert "转账" not in out["answer"]


def test_chitchat_and_clarify_prompts_and_mocks():
    assert "禁止" in CHITCHAT_SYSTEM_PROMPT
    assert "法条" in CHITCHAT_SYSTEM_PROMPT
    assert "法律咨询" in CHITCHAT_SYSTEM_PROMPT
    assert "理解" in CLARIFY_SYSTEM_PROMPT
    assert "领域" in CLARIFY_SYSTEM_PROMPT
    assert "法条" in build_chitchat_user_prompt(query="你好")
    clarify_p = build_clarify_user_prompt(query="想问点事")
    assert "理解" in clarify_p
    assert "领域" in clarify_p or "类型" in clarify_p

    chat = _mock_answer({"query": "你好", "intent": "chitchat"})
    assert "LawBot" in chat
    assert "## 简单说" not in chat

    clarify = _mock_answer({"query": "想问点事", "intent": "ambiguous"})
    assert "理解" in clarify
    assert "法律问题类型" not in clarify
    assert "法律领域" not in clarify
    assert "## 法律上大概怎么看" not in clarify


def test_hurt_oral_mock_is_legal_not_clarify():
    text = _mock_answer(
        {
            "query": "我被人打了怎么讹他",
            "collected": "我被人打了怎么讹他",
            "intent": "legal",
            "user_issue_plain": "被人打了想依法索赔",
            "citations": [],
        }
    )
    assert "## 简单说" in text
    assert any(k in text for k in ("报警", "赔偿", "伤害", "伤"))
    assert "法律问题领域" not in text
    assert "法律问题类型" not in text
    assert "敲诈" in text or "合法" in text


def test_out_of_scope_prompts_and_mocks():
    assert "短拒" in OUT_OF_SCOPE_SYSTEM_PROMPT or "礼貌" in OUT_OF_SCOPE_SYSTEM_PROMPT
    assert "法律咨询" in OUT_OF_SCOPE_SYSTEM_PROMPT
    assert "法条" in OUT_OF_SCOPE_SYSTEM_PROMPT
    assert "超出" in build_out_of_scope_user_prompt(query="红烧肉怎么做")
    assert "领域外" in ANSWER_SYSTEM_PROMPT or "超出范围" in ANSWER_SYSTEM_PROMPT

    oos = _mock_answer({"query": "帮我写个排序算法", "intent": "out_of_scope"})
    assert "法律咨询" in oos
    assert "LawBot" in oos
    assert "## 简单说" not in oos
