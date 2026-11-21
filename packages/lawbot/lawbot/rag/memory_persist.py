from __future__ import annotations

import json
import logging
from pathlib import Path

from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore

logger = logging.getLogger(__name__)

RECORDS_NAME = "records.jsonl"
VECTORS_NAME = "vectors.json"


def memory_index_paths(memory_dir: str | Path) -> tuple[Path, Path]:
    root = Path(memory_dir).expanduser().resolve()
    return root / RECORDS_NAME, root / VECTORS_NAME


def save_memory_index(
    vector_store: InMemoryVectorStore,
    bm25_store: InMemoryBM25Store,
    memory_dir: str | Path,
) -> int:
    """Persist in-memory stores to disk. Returns number of records written."""
    _ = bm25_store  # bm25 rebuilt from records on load
    root = Path(memory_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    records_path, vectors_path = memory_index_paths(root)

    records = [rec for _, rec in vector_store._items]
    vectors = [vec for vec, _ in vector_store._items]

    with records_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(rec.model_dump_json() + "\n")
    vectors_path.write_text(json.dumps(vectors, ensure_ascii=False), encoding="utf-8")
    logger.info("saved memory index dir=%s count=%s", root, len(records))
    return len(records)


def load_memory_index(
    memory_dir: str | Path,
    *,
    vector_store: InMemoryVectorStore | None = None,
    bm25_store: InMemoryBM25Store | None = None,
) -> tuple[InMemoryVectorStore, InMemoryBM25Store, int]:
    """Load disk index into stores (or new ones). Returns (vec, bm25, count)."""
    vec = vector_store or InMemoryVectorStore()
    bm25 = bm25_store or InMemoryBM25Store()
    records_path, vectors_path = memory_index_paths(memory_dir)
    if not records_path.is_file() or not vectors_path.is_file():
        logger.info("memory index missing at %s; starting empty", records_path.parent)
        return vec, bm25, 0

    records: list[KnowledgeChunk] = []
    with records_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(KnowledgeChunk.from_legacy_dict(data))
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    if not isinstance(vectors, list) or len(vectors) != len(records):
        raise ValueError(
            f"memory index corrupt: {len(records)} records vs "
            f"{len(vectors) if isinstance(vectors, list) else 'bad'} vectors"
        )

    vec._items.clear()
    bm25._docs.clear()
    if records:
        vec.upsert(records, vectors)
        bm25.upsert(records)
    logger.info("loaded memory index dir=%s count=%s", records_path.parent, len(records))
    return vec, bm25, len(records)
