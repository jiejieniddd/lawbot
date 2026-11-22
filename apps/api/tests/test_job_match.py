from __future__ import annotations

from lawbot.agent.graph import (
    _career_intent_subtype,
    _hit_matches_query_topic,
    _kb_domains_for_intent,
    _mock_out_of_scope,
)
from lawbot.agent.tools import ToolContext, execute_tool, load_role_skill_map
from lawbot.knowledge.importers.ai_job_zh import row_to_chunk
from lawbot.rag.fake import FakeRetriever


JD_A = """
Python 后端开发工程师
岗位职责：负责 FastAPI 服务开发与 Redis 缓存
任职要求：熟悉 Python、FastAPI、PostgreSQL、Docker
"""

JD_B = """
计算机视觉算法工程师
岗位职责：负责目标检测与 OpenCV 视觉算法落地
任职要求：精通 C++、OpenCV、CUDA、PyTorch
"""


def test_ai_job_chunk_structure():
    chunk = row_to_chunk(
        {
            "_c0": "深度学习算法工程师",
            "text": "Python,PyTorch 岗位职责：负责模型训练。任职要求：熟悉 CNN。",
        }
    )
    assert chunk is not None
    assert chunk.domain == "job_skills"
    assert chunk.source_id.startswith("ai_job:")
    assert "|" in chunk.chunk_text
    assert "深度学习算法工程师" in chunk.chunk_text


def test_dual_jd_match_scores_differ():
    ctx = ToolContext(
        retriever=FakeRetriever(),
        active_resume={
            "skills": ["Python", "FastAPI", "Redis", "Docker"],
            "intent": "后端",
            "structured": {
                "skills": ["Python", "FastAPI", "Redis", "Docker"],
                "intent": "后端",
            },
        },
    )
    a = execute_tool("match_job", {"jd_text": JD_A, "top_k": 3}, ctx)
    b = execute_tool("match_job", {"jd_text": JD_B, "top_k": 3}, ctx)
    assert a.ok and b.ok
    assert a.output["match_score"] > b.output["match_score"]
    assert "FastAPI" in a.output["matched"] or "Python" in a.output["matched"]
    assert any(g in b.output["gaps"] for g in ("C++", "OpenCV", "CUDA", "PyTorch"))


def test_skill_gap_can_use_role_skill_map():
    mapping = load_role_skill_map()
    # Map should exist after Phase3 import; if empty still ok to run tool
    ctx = ToolContext(
        retriever=FakeRetriever(),
        active_resume={"skills": ["Python"], "structured": {"skills": ["Python"], "intent": "算法工程师"}},
    )
    out = execute_tool("skill_gap_plan", {"target_role": "算法工程师", "top_k": 3}, ctx)
    assert out.ok
    assert "plan" in out.output
    if mapping:
        assert out.output.get("role_skill_map_used") is True or out.output.get("market_skills") is not None


def test_job_match_intent_and_auto_apply_oos():
    assert _career_intent_subtype("这份JD和我匹配吗") == "job_match"
    assert _career_intent_subtype("这类岗位市场要什么技能") == "job_market"
    text = _mock_out_of_scope("帮我自动投 Boss")
    assert "不能协助" in text or "不能" in text
    assert "checklist" in text.lower() or "检查清单" in text


def test_kb_domains_career_advice_prefers_job_skills():
    domains = _kb_domains_for_intent("career_advice")
    assert domains[0] == "job_skills"
    assert "interview_qa" in domains
    assert _kb_domains_for_intent("interview_qa") == ["interview_qa"]


def test_mock_interview_domain_blocked_from_main_search():
    from lawbot.knowledge.importers import MAIN_SEARCH_DOMAIN_BLOCKLIST

    assert "mock_interview" in MAIN_SEARCH_DOMAIN_BLOCKLIST
    assert "self_test" in MAIN_SEARCH_DOMAIN_BLOCKLIST


def test_topic_filter_no_domain_freepass():
    hit = {
        "domain": "interview_qa",
        "law_name": "微博运营经验分享",
        "text": "如何做好内容创作与粉丝互动",
        "score": 0.5,
    }
    assert _hit_matches_query_topic(hit, "Python 后端 Redis", q_keys=["python", "redis", "后端"]) is False
    hit2 = {
        "domain": "job_skills",
        "law_name": "Python 后端开发",
        "text": "熟悉 Redis 与 FastAPI",
        "score": 0.5,
    }
    assert _hit_matches_query_topic(hit2, "Python 后端 Redis", q_keys=["python", "redis", "后端"]) is True
