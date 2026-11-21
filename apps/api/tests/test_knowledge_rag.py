from __future__ import annotations

from lawbot.domain.schemas import Citation
from lawbot.knowledge.hf_import import build_chunk, filter_article_row, iter_filtered_articles, row_to_record
from lawbot.knowledge.indexer import run_import
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.factory import (
    RetrieverSettings,
    build_retriever,
    get_memory_stores,
    reset_memory_stores_for_tests,
)
from lawbot.rag.hybrid import HybridRetriever, reciprocal_rank_fusion
from lawbot.rag.memory_persist import load_memory_index, save_memory_index
from lawbot.rag.fake import FakeRetriever


SAMPLE_ROWS = [
    {
        "id": "a1",
        "doc_id": "d1",
        "title": "中华人民共和国合同法",
        "article_no": "1",
        "article_no_cn": "第一条",
        "text": "为了保护合同当事人的合法权益，制定本法。",
        "category": "法律",
        "status": "有效",
        "jurisdiction": "全国",
        "source_url": "https://example.com/a1",
        "filename_date": "1999-03-15",
    },
    {
        "id": "a2",
        "doc_id": "d2",
        "title": "某市条例",
        "article_no": "1",
        "article_no_cn": "第一条",
        "text": "地方法规示例。",
        "category": "地方性法规",
        "status": "有效",
        "jurisdiction": "某市",
        "source_url": "https://example.com/a2",
        "filename_date": "2020-01-01",
    },
    {
        "id": "a3",
        "doc_id": "d3",
        "title": "废止法",
        "article_no": "1",
        "article_no_cn": "第一条",
        "text": "已废止。",
        "category": "法律",
        "status": "废止",
        "jurisdiction": "全国",
        "source_url": "https://example.com/a3",
        "filename_date": "2010-01-01",
    },
    {
        "id": "a4",
        "doc_id": "d4",
        "title": "最高人民法院司法解释",
        "article_no": "2",
        "article_no_cn": "第二条",
        "text": "合同违约责任的解释。",
        "category": "司法解释",
        "status": "有效",
        "jurisdiction": "全国",
        "source_url": "https://example.com/a4",
        "filename_date": "2021-01-01",
    },
]


def test_filter_and_chunk():
    assert filter_article_row(SAMPLE_ROWS[0]) is True
    assert filter_article_row(SAMPLE_ROWS[1]) is False
    assert filter_article_row(SAMPLE_ROWS[2]) is False
    chunk = build_chunk("合同法", "第一条", "保护合法权益")
    assert chunk == "《合同法》第一条 保护合法权益"
    rec = row_to_record(SAMPLE_ROWS[0])
    assert rec.source_id == "a1"
    assert rec.law_name == "中华人民共和国合同法"
    assert "第一条" in rec.chunk_text
    assert rec.effective_date == "1999-03-15"


def test_iter_filtered_max_rows():
    records = list(iter_filtered_articles(rows=SAMPLE_ROWS, max_rows=1))
    assert len(records) == 1
    assert records[0].source_id == "a1"
    all_ok = list(iter_filtered_articles(rows=SAMPLE_ROWS, max_rows=0))
    assert {r.source_id for r in all_ok} == {"a1", "a4"}


def test_rrf_fusion_prefers_shared_hits():
    c1 = Citation(law_name="A", article_no="1", text="t1", source_id="s1")
    c2 = Citation(law_name="B", article_no="2", text="t2", source_id="s2")
    c3 = Citation(law_name="C", article_no="3", text="t3", source_id="s3")
    vec = [
        RetrievedChunk(citation=c1, score=0.9),
        RetrievedChunk(citation=c2, score=0.8),
    ]
    bm25 = [
        RetrievedChunk(citation=c3, score=5.0),
        RetrievedChunk(citation=c1, score=4.0),
    ]
    fused = reciprocal_rank_fusion([vec, bm25], k=60, top_k=3)
    assert fused[0].citation.source_id == "s1"
    assert {c.citation.source_id for c in fused} == {"s1", "s2", "s3"}


def test_hybrid_empty_backends_return_empty_not_fake():
    r = HybridRetriever()
    hits = r.retrieve("劳动合同", top_k=3)
    assert hits == []
    assert all(not h.citation.source_id.startswith("fake-") for h in hits)


def test_fake_mode_still_returns_fake_ids():
    r = build_retriever(RetrieverSettings(mode="fake"))
    assert isinstance(r, FakeRetriever)
    hits = r.retrieve("劳动合同", top_k=3)
    assert hits
    assert any(h.citation.source_id.startswith("fake-") for h in hits)


def test_memory_import_and_hybrid_retrieve(tmp_path):
    reset_memory_stores_for_tests()
    memory_dir = tmp_path / "rag_memory"
    stats = run_import(
        max_rows=10,
        rows=SAMPLE_ROWS,
        index_backend="memory",
        memory_dir=str(memory_dir),
        embedding_mode="fake",
        batch_size=2,
        recreate=True,
    )
    assert stats["indexed"] == 2
    assert stats["backend"] == "memory"
    reset_memory_stores_for_tests()
    retriever = build_retriever(
        RetrieverSettings(mode="memory", embedding_mode="fake", memory_dir=str(memory_dir))
    )
    hits = retriever.retrieve("合同 合法权益", top_k=2)
    assert hits
    assert hits[0].citation.source_id in {"a1", "a4"}
    assert not hits[0].citation.source_id.startswith("fake-")
    assert hits[0].citation.law_name
    assert hits[0].citation.article_no
    assert hits[0].citation.text


def test_memory_persist_roundtrip(tmp_path):
    reset_memory_stores_for_tests()
    memory_dir = tmp_path / "persist"
    run_import(
        rows=SAMPLE_ROWS,
        index_backend="memory",
        memory_dir=str(memory_dir),
        embedding_mode="fake",
        recreate=True,
    )
    vec, bm25 = get_memory_stores()
    assert len(vec._items) == 2
    save_memory_index(vec, bm25, memory_dir)
    reset_memory_stores_for_tests()
    loaded_vec, loaded_bm25, count = load_memory_index(memory_dir)
    assert count == 2
    hits = loaded_vec.search(loaded_vec._items[0][0], top_k=1)
    assert hits
    assert not hits[0].citation.source_id.startswith("fake-")
    assert loaded_bm25.search("合同", top_k=1)


def test_indexer_opensearch_degraded(monkeypatch, tmp_path):
    from lawbot.knowledge import indexer as indexer_mod

    class BoomOS:
        def __init__(self, *args, **kwargs):
            pass

        def ensure_index(self, recreate: bool = False) -> None:
            raise RuntimeError("opensearch down")

        def upsert(self, records):
            raise RuntimeError("should not be called")

    class FakeQdrant:
        def __init__(self, *args, **kwargs):
            self.upserted = 0

        def ensure_collection(self, recreate: bool = False) -> None:
            return None

        def upsert(self, records, vectors):
            self.upserted += len(records)
            return len(records)

    monkeypatch.setattr(indexer_mod, "OpenSearchArticleStore", BoomOS)
    fake_q = FakeQdrant()
    monkeypatch.setattr(indexer_mod, "QdrantArticleStore", lambda **kwargs: fake_q)

    stats = run_import(
        rows=SAMPLE_ROWS,
        index_backend="qdrant",
        embedding_mode="fake",
        memory_dir=str(tmp_path),
    )
    assert stats["indexed"] == 2
    assert stats["backend"] == "qdrant"
    assert stats["opensearch"] == "degraded"
    assert fake_q.upserted == 2


def _admin_headers(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_knowledge_import_job_create_and_get(client, admin_user):
    headers = _admin_headers(client, admin_user)
    created = client.post("/api/admin/knowledge-import-jobs", headers=headers, json={})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending"
    assert body["config"]["max_rows"] == 200
    assert body["config"]["subset"] == "train"
    assert body["config"].get("source") == "interview_zh"
    assert body["config"].get("domain") == "interview_qa"
    job_id = body["id"]
    got = client.get(f"/api/admin/knowledge-import-jobs/{job_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["id"] == job_id


def test_worker_claim_and_finish_job(db_session, admin_user, monkeypatch):
    from app.config import get_settings
    from lawbot.db.models import KnowledgeImportJob
    from lawbot.db.session import get_sessionmaker
    from lawbot.domain.schemas import ImportJobStatus
    from worker import main as worker_main

    db_url = get_settings().database_url
    factory = get_sessionmaker(db_url)
    monkeypatch.setattr(worker_main, "get_sessionmaker", lambda _url: factory)

    job = KnowledgeImportJob(
        status=ImportJobStatus.PENDING,
        source="hf:test",
        config={"max_rows": 2},
        stats={},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    job_id = job.id

    claimed = worker_main.claim_next_job(db_url)
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.status == ImportJobStatus.RUNNING

    worker_main.finish_job(
        db_url,
        job_id,
        status=ImportJobStatus.SUCCEEDED,
        stats={"indexed": 2, "read": 2},
    )
    db_session.expire_all()
    refreshed = db_session.get(KnowledgeImportJob, job_id)
    assert refreshed is not None
    assert refreshed.status == ImportJobStatus.SUCCEEDED
    assert refreshed.stats["indexed"] == 2


def test_knowledge_search_api(client, admin_user, monkeypatch):
    from app.routers.admin import knowledge_search as search_mod

    class StubRetriever:
        def retrieve(self, query: str, top_k: int = 3):
            return [
                RetrievedChunk(
                    citation=Citation(
                        law_name="中华人民共和国合同法",
                        article_no="第一条",
                        text="为了保护合同当事人的合法权益，制定本法。",
                        source_id="a1",
                        category="法律",
                    ),
                    score=1.0,
                )
            ][:top_k]

    monkeypatch.setattr(search_mod, "get_retriever", lambda: StubRetriever())
    headers = _admin_headers(client, admin_user)
    get_resp = client.get("/api/admin/knowledge/search", headers=headers, params={"q": "合同"})
    assert get_resp.status_code == 200
    results = get_resp.json()["results"]
    assert results[0]["source_id"] == "a1"
    assert results[0]["law_name"]
    assert results[0]["article_no"]
    assert results[0]["text"]

    post_resp = client.post(
        "/api/admin/knowledge/search",
        headers=headers,
        json={"q": "合同", "top_k": 1},
    )
    assert post_resp.status_code == 200
    assert len(post_resp.json()["results"]) == 1
