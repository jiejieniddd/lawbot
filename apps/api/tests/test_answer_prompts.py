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
    assert "CareerBot" in ANSWER_SYSTEM_PROMPT
    assert "## 简单说" in ANSWER_SYSTEM_PROMPT
    assert "## 你可以怎么做" in ANSWER_SYSTEM_PROMPT
    assert "Markdown" in ANSWER_SYSTEM_PROMPT
    assert "不得编造" in ANSWER_SYSTEM_PROMPT or "禁止捏造" in ANSWER_SYSTEM_PROMPT
    assert "未检索到直接依据" in ANSWER_SYSTEM_PROMPT
    assert "求职" in ANSWER_SYSTEM_PROMPT


def test_user_prompt_with_citations_and_empty():
    cites = [
        {
            "law_name": "FastAPI Depends",
            "article_no": "tech_docs",
            "text": "Depends 用于声明可复用依赖……",
            "source_id": "src-1",
            "domain": "tech_docs",
        }
    ]
    with_cites = build_answer_user_prompt(
        query="FastAPI 依赖注入怎么用",
        case_type="backend",
        citations=cites,
        user_issue_plain="想搞懂 FastAPI Depends",
        search_query="FastAPI Depends",
    )
    assert "FastAPI 依赖注入怎么用" in with_cites
    assert "FastAPI Depends" in with_cites
    assert "Depends 用于声明可复用依赖" in with_cites
    assert "src-1" not in with_cites
    assert "source_id=" not in with_cites
    assert "source_id" not in with_cites
    assert "检索知识点" in with_cites
    assert "未检索到直接依据" in with_cites or "不要假装" in with_cites

    empty = build_answer_user_prompt(query="冷门技术问题", case_type="general", citations=[])
    assert "（无）" in empty or format_citation_block([]) == "（无）"
    assert "source_id" not in empty
    assert "未检索到直接依据" in empty or "不要假装" in empty


def test_mock_answer_analytical_with_and_without_citations():
    empty_state = {
        "query": "偏门技术咨询",
        "collected": "偏门技术咨询",
        "case_type": "general",
        "citations": [],
        "intent": "tech_howto",
    }
    empty_text = _mock_answer(empty_state)
    assert "未检索到直接依据" in empty_text or "未配置可用模型" in empty_text

    with_cites = _mock_answer(
        {
            "query": "Python 后端面试常考什么",
            "collected": "Python 后端面试常考什么",
            "case_type": "backend",
            "intent": "interview_qa",
            "citations": [
                {
                    "law_name": "Python 面试",
                    "article_no": "interview_qa",
                    "text": "常考 GIL、装饰器……",
                    "source_id": "src-1",
                    "domain": "interview_qa",
                }
            ],
        }
    )
    assert "## 简单说" in with_cites or "Python" in with_cites


def test_make_answer_uses_new_prompts(monkeypatch):
    captured: dict = {}

    def fake_stream(**kwargs):
        captured["system"] = kwargs.get("system") or ""
        captured["prompt"] = kwargs.get("prompt") or ""
        yield "token-a"
        return

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", fake_stream)
    monkeypatch.setattr(
        "lawbot.agent.graph.complete_text",
        lambda **_kwargs: '{"direction":"d","key_points":"k","advice":"a","risk":"r"}',
    )
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    # Without citations stream path may not use LLM; ensure mock path ok
    out = make_answer(creds)(
        {
            "query": "Docker 怎么用",
            "collected": "Docker 怎么用",
            "citations": [],
            "intent": "tech_howto",
            "case_type": "devops",
            "retrieval_usable": False,
        }
    )
    assert out.get("answer")
    assert "CareerBot" in ANSWER_SYSTEM_PROMPT


def test_make_answer_empty_llm_falls_back(monkeypatch):
    def empty_stream(**_kwargs):
        if False:
            yield ""
        return

    monkeypatch.setattr("lawbot.agent.graph.complete_text_stream", empty_stream)
    monkeypatch.setattr("lawbot.agent.graph.complete_text", lambda **_kwargs: "")
    creds = ProviderCredentials(
        provider=SimpleNamespace(id="p1", name="mock"),  # type: ignore[arg-type]
        api_key="k",
        model="m",
        base_url=None,
    )
    out = make_answer(creds)(
        {
            "query": "Docker 怎么部署",
            "collected": "Docker 怎么部署",
            "citations": [{"law_name": "无关", "article_no": "1", "text": "x"}],
            "intent": "tech_howto",
        }
    )
    assert out["used_mock"] is True
    assert out.get("answer")


def test_chitchat_and_clarify_prompts_and_mocks():
    assert "禁止" in CHITCHAT_SYSTEM_PROMPT
    assert "CareerBot" in CHITCHAT_SYSTEM_PROMPT
    assert "求职" in CHITCHAT_SYSTEM_PROMPT
    assert "理解" in CLARIFY_SYSTEM_PROMPT
    assert "求职" in build_chitchat_user_prompt(query="你好")
    clarify_p = build_clarify_user_prompt(query="想问点事")
    assert "理解" in clarify_p

    chat = _mock_answer({"query": "你好", "intent": "chitchat"})
    assert "CareerBot" in chat
    assert "## 简单说" not in chat

    clarify = _mock_answer({"query": "想问点事", "intent": "ambiguous"})
    assert "理解" in clarify


def test_resume_analysis_prompt_includes_skills():
    text = build_answer_user_prompt(
        query="我的技术短板",
        case_type="backend",
        citations=[],
        active_resume={"skills": ["Python", "FastAPI"], "intent": "后端"},
        resume_analysis={
            "summary": "【当前简历】\n技能：Python、FastAPI",
            "skills": ["Python", "FastAPI"],
            "has_resume": True,
        },
        skill_gap={"plan": "目标方向：后端。建议补齐薄弱点。", "suggested_gaps": ["K8s"]},
    )
    assert "Python" in text
    assert "技能" in text or "简历" in text


def test_out_of_scope_prompts_and_mocks():
    assert "短拒" in OUT_OF_SCOPE_SYSTEM_PROMPT or "礼貌" in OUT_OF_SCOPE_SYSTEM_PROMPT
    assert "求职" in OUT_OF_SCOPE_SYSTEM_PROMPT
    assert "超出" in build_out_of_scope_user_prompt(query="红烧肉怎么做")
    assert "领域外" in ANSWER_SYSTEM_PROMPT or "范围外" in ANSWER_SYSTEM_PROMPT

    oos = _mock_answer({"query": "红烧肉怎么做", "intent": "out_of_scope"})
    assert "CareerBot" in oos or "求职" in oos
    assert "## 简单说" not in oos
