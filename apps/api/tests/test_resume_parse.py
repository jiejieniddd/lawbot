from __future__ import annotations

from pathlib import Path

from app.services.resume_parse import NullOcr, ParseResult, parse_resume_file, structure_from_text
from lawbot.agent.tools import ToolContext, execute_tool
from lawbot.knowledge.importers.cmmlu_cs import row_to_chunk
from lawbot.knowledge.importers.hive_corpus import row_to_chunk as hive_row_to_chunk


def test_structure_from_text_extracts_skills():
    text = """
    求职意向：Python 后端开发
    技能：Python、FastAPI、Docker、Redis、PostgreSQL
    项目：LawBot 求职助手
    """
    profile = structure_from_text(text)
    assert "Python" in profile.skills
    assert "FastAPI" in profile.skills
    assert "后端" in profile.intent or profile.intent


def test_png_without_ocr_fails_ocr(tmp_path: Path):
    png = tmp_path / "r.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    result = parse_resume_file(png, mime="image/png", ocr=NullOcr())
    assert isinstance(result, ParseResult)
    assert result.status == "failed_ocr"


def test_analyze_resume_and_followup_tools():
    from lawbot.rag.fake import FakeRetriever

    ctx = ToolContext(
        retriever=FakeRetriever(),
        active_resume={
            "skills": ["Python", "FastAPI"],
            "intent": "后端",
            "structured": {
                "skills": ["Python", "FastAPI"],
                "intent": "后端",
                "projects": [],
                "education": [],
                "experience": [],
            },
        },
    )
    ar = execute_tool("analyze_resume", {"focus": "skills"}, ctx)
    assert ar.ok
    assert ar.output["has_resume"] is True
    assert "Python" in ar.output["skills"]

    fu = execute_tool("interview_followup", {"topic": "索引", "top_k": 3}, ctx)
    assert fu.ok
    assert len(fu.output["directions"]) >= 1


def test_hive_and_cmmlu_importers():
    hive = hive_row_to_chunk(
        {"title": "Indexing pitfalls", "content": "Watch for off-by-one", "tags": ["databases"]}
    )
    assert hive is not None
    assert hive.domain == "gotchas"

    cm = row_to_chunk(
        {
            "subject": "computer_science",
            "Question": "What is a binary tree?",
            "A": "Linear",
            "B": "Hierarchical",
            "C": "Graph only",
            "D": "Hash",
            "Answer": "B",
        }
    )
    assert cm is not None
    assert cm.domain == "self_test"
    assert cm.meta.get("options")
