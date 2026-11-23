from __future__ import annotations

import csv
import json

from lawbot.agent.graph import _is_role_requirements_query
from lawbot.agent.tools import _market_skills_for_role
from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.knowledge.embedder import fake_embed
from lawbot.rag.memory_persist import load_memory_index, save_memory_index
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore
from scripts.build_computing_memory import build, keep_existing


def _record(source_id: str, domain: str, title: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        source_id=source_id, domain=domain, title=title,
        text=title, chunk_text=title, category=domain,
    )


def test_generic_interview_removed_but_technical_question_kept():
    assert not keep_existing(_record("soft", "interview_qa", "你如何与团队合作？"))
    assert keep_existing(_record("tech", "interview_qa", "Java 多线程如何处理并发？"))
    assert keep_existing(_record("job", "job_skills", "Python 后端开发"))
    assert not keep_existing(_record("law", "legacy_law", "合同法"))


def test_role_requirement_detection():
    assert _is_role_requirements_query("我想面试 Java 全栈开发，应当具备哪些技术栈？")
    assert _is_role_requirements_query("软件测试工程师岗位要求")
    assert not _is_role_requirements_query("Spring 事务如何工作？")


def test_role_skill_map_uses_specific_computing_roles():
    assert "Java" in _market_skills_for_role("Java全栈开发")
    assert "React" in _market_skills_for_role("前端开发工程师")
    assert "Pytest" in _market_skills_for_role("软件测试工程师")
    assert _market_skills_for_role("厨师") == []


def test_build_filters_old_index_and_adds_only_computing_occupation(tmp_path):
    source = tmp_path / "old"
    output = tmp_path / "new"
    onet = tmp_path / "onet"
    onet.mkdir()
    rows = [
        _record("soft", "interview_qa", "你如何与团队合作？"),
        _record("tech", "interview_qa", "Java 多线程如何处理并发？"),
        _record("law", "legacy_law", "合同法"),
        _record("job", "job_skills", "算法工程师"),
    ]
    vectors = [fake_embed(row.chunk_text) for row in rows]
    vector = InMemoryVectorStore()
    bm25 = InMemoryBM25Store()
    vector.upsert(rows, vectors)
    bm25.upsert(rows)
    save_memory_index(vector, bm25, source)

    (onet / "occupation_data.json").write_text(json.dumps({"row": [
        {"onetsoc_code": "15-1252.00", "title": "Software Developers", "description": "Design software."},
        {"onetsoc_code": "41-2011.00", "title": "Cashiers", "description": "Handle payment."},
    ]}), encoding="utf-8")
    with (onet / "software_skills.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["O*NET-SOC Code", "Workplace Example", "In Demand", "Hot Technology"])
        writer.writeheader()
        writer.writerow({"O*NET-SOC Code": "15-1252.00", "Workplace Example": "Java", "In Demand": "Y", "Hot Technology": "Y"})
        writer.writerow({"O*NET-SOC Code": "41-2011.00", "Workplace Example": "Cash register", "In Demand": "Y", "Hot Technology": "N"})
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"15-1252.00": ["Java全栈开发", "后端开发工程师"]}), encoding="utf-8")

    stats = build(source, onet, output, aliases)
    assert stats["removed"] == 2
    assert stats["onet_profiles"] == 1
    out_vec, out_bm25, count = load_memory_index(output)
    assert count == 3
    assert {record.source_id for _, record in out_vec._items} == {"tech", "job", "onet31:15-1252.00"}
    hit = out_bm25.search("Java 全栈 开发 技术栈", top_k=1, domains=["job_skills"])[0]
    assert hit.citation.source_id == "onet31:15-1252.00"
    rebuilt = tmp_path / "rebuilt"
    second_stats = build(output, onet, rebuilt, aliases)
    assert second_stats["total"] == count
    _, _, rebuilt_count = load_memory_index(rebuilt)
    assert rebuilt_count == count
