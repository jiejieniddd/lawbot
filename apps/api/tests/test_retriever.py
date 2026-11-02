from lawbot.rag.fake import FakeRetriever


def test_fake_retriever_labor():
    r = FakeRetriever()
    chunks = r.retrieve("公司拖欠工资怎么办", top_k=2)
    assert len(chunks) == 2
    assert chunks[0].citation.source_id
    assert "劳动" in chunks[0].citation.law_name or chunks[0].score >= 0.5
