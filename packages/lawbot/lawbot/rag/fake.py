from __future__ import annotations

from lawbot.domain.schemas import Citation
from lawbot.rag.base import RetrievedChunk


class FakeRetriever:
    """Deterministic stub retriever for skeleton builds."""

    FAKE_DOCS: list[Citation] = [
        Citation(
            law_name="中华人民共和国劳动合同法",
            article_no="第三十八条",
            text="用人单位有下列情形之一的，劳动者可以解除劳动合同：…未及时足额支付劳动报酬的。",
            source_id="fake-labor-38",
            effective_date="2008-01-01",
            category="labor",
            jurisdiction="CN",
            source_url="https://example.local/labor-38",
        ),
        Citation(
            law_name="中华人民共和国民法典",
            article_no="第五百七十七条",
            text="当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
            source_id="fake-civil-577",
            effective_date="2021-01-01",
            category="civil",
            jurisdiction="CN",
            source_url="https://example.local/civil-577",
        ),
        Citation(
            law_name="中华人民共和国消费者权益保护法",
            article_no="第五十五条",
            text="经营者提供商品或者服务有欺诈行为的，应当按照消费者的要求增加赔偿其受到的损失…",
            source_id="fake-consumer-55",
            effective_date="2014-03-15",
            category="consumer",
            jurisdiction="CN",
            source_url="https://example.local/consumer-55",
        ),
    ]

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        q = query.lower()
        scored: list[RetrievedChunk] = []
        for doc in self.FAKE_DOCS:
            score = 0.5
            if any(k in q for k in ("劳动", "工资", "解雇", "labor")):
                if "劳动" in doc.law_name:
                    score = 1.0
            elif any(k in q for k in ("合同", "违约", "contract")):
                if "民法典" in doc.law_name:
                    score = 1.0
            elif any(k in q for k in ("消费", "欺诈", "consumer")):
                if "消费者" in doc.law_name:
                    score = 1.0
            scored.append(RetrievedChunk(citation=doc, score=score))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
