from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.knowledge.importers import (
    ai_job_zh,
    cmmlu_cs,
    dev_docs_en,
    hive_corpus,
    interview_zh,
)

ImporterFn = Callable[..., Iterator[KnowledgeChunk]]

REGISTRY: dict[str, ImporterFn] = {
    "interview_zh": interview_zh.iter_interview_chunks,
    "dev_docs_en": dev_docs_en.iter_dev_doc_chunks,
    "hive_corpus": hive_corpus.iter_hive_chunks,
    "cmmlu_cs": cmmlu_cs.iter_cmmlu_chunks,
    "ai_job_zh": ai_job_zh.iter_ai_job_chunks,
}

SOURCE_DEFAULT_DATASET: dict[str, str] = {
    "interview_zh": "data/hf/Chinese_interview_large",
    # Prefer train parquet under data/; fall back to test split for low-spec smoke.
    "dev_docs_en": "data/hf/dev-knowledge-base/data",
    "hive_corpus": "data/hf/the-hive-corpus",
    "cmmlu_cs": "data/hf/cmmlu",
    "ai_job_zh": "data/hf/AI_Job_DataSet_1000_list",
}

SOURCE_DOMAIN: dict[str, str] = {
    "interview_zh": interview_zh.DOMAIN,
    "dev_docs_en": dev_docs_en.DOMAIN,
    "hive_corpus": hive_corpus.DOMAIN,
    "cmmlu_cs": cmmlu_cs.DOMAIN,
    "ai_job_zh": ai_job_zh.DOMAIN,
}

# Domains never mixed into main search_kb RRF.
MAIN_SEARCH_DOMAIN_BLOCKLIST: frozenset[str] = frozenset({"self_test"})


def iter_source_chunks(
    source: str,
    rows: Iterator[Mapping[str, Any]],
    *,
    max_rows: int = 500,
    allowlist: Iterable[str] | None = None,
) -> Iterator[KnowledgeChunk]:
    key = (source or "").strip()
    if key not in REGISTRY:
        raise ValueError(f"unknown import source={source!r}; expected one of {sorted(REGISTRY)}")
    fn = REGISTRY[key]
    if key == "dev_docs_en":
        yield from fn(rows, max_rows=max_rows, allowlist=allowlist)
    else:
        yield from fn(rows, max_rows=max_rows)
