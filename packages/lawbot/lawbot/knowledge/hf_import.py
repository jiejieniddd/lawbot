from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from lawbot.domain.schemas import Citation
from lawbot.knowledge.chunk import KnowledgeChunk

ALLOWED_CATEGORIES = frozenset({"法律", "行政法规", "司法解释"})
# CareerBot default (Domain A). Legacy law hub id kept only for explicit legacy imports.
DEFAULT_DATASET = "data/hf/Chinese_interview_large"
DEFAULT_HUB_DATASET = "zhangjun640/Chinese_interview_large"
DEFAULT_SUBSET = "train"
LEGACY_LAW_DATASET = "senry5433/china-effective-laws-regulations"
LEGACY_LAW_SUBSET = "articles"


class ArticleRecord(BaseModel):
    source_id: str
    doc_id: str | None = None
    law_name: str
    article_no: str
    article_no_num: str | None = None
    text: str
    chunk_text: str
    category: str | None = None
    jurisdiction: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    status: str | None = None

    def to_citation(self) -> Citation:
        return Citation(
            law_name=self.law_name,
            article_no=self.article_no,
            text=self.text,
            source_id=self.source_id,
            effective_date=self.effective_date,
            category=self.category,
            jurisdiction=self.jurisdiction,
            source_url=self.source_url,
            status=self.status,
        )


def build_chunk(title: str, article_no_cn: str, text: str) -> str:
    return f"《{title}》{article_no_cn} {text}"


def filter_article_row(
    row: Mapping[str, Any],
    *,
    categories: frozenset[str] = ALLOWED_CATEGORIES,
) -> bool:
    if row.get("status") != "有效":
        return False
    return row.get("category") in categories


def row_to_record(row: Mapping[str, Any]) -> ArticleRecord:
    title = str(row.get("title") or "")
    article_no_cn = str(row.get("article_no_cn") or row.get("article_no") or "")
    text = str(row.get("text") or "")
    source_id = str(row.get("id") or f"{row.get('doc_id')}:{article_no_cn}")
    source_url = row.get("source_url") or "https://flk.npc.gov.cn/"
    return ArticleRecord(
        source_id=source_id,
        doc_id=str(row["doc_id"]) if row.get("doc_id") is not None else None,
        law_name=title,
        article_no=article_no_cn,
        article_no_num=str(row["article_no"]) if row.get("article_no") is not None else None,
        text=text,
        chunk_text=build_chunk(title, article_no_cn, text),
        category=row.get("category"),
        jurisdiction=row.get("jurisdiction"),
        source_url=str(source_url) if source_url else None,
        effective_date=str(row["filename_date"]) if row.get("filename_date") else None,
        status=row.get("status"),
    )


def _load_dataset_rows(dataset_id: str, subset: str) -> Iterator[Mapping[str, Any]]:
    """Load from local disk/parquet path or Hugging Face Hub id."""
    from datasets import load_dataset, load_from_disk

    path = Path(dataset_id).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    if resolved.exists():
        if resolved.is_file() and resolved.suffix.lower() == ".parquet":
            ds = load_dataset("parquet", data_files=str(resolved), split="train")
            for i in range(len(ds)):
                yield ds[i]
            return
        if resolved.is_file() and resolved.suffix.lower() == ".jsonl":
            import json as _json

            for line in resolved.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = _json.loads(line)
                if isinstance(row, Mapping):
                    yield row
            return
        if resolved.is_dir():
            jsonl_files = sorted(resolved.glob("*.jsonl"))
            if jsonl_files:
                import json as _json

                for jp in jsonl_files:
                    for line in jp.read_text(encoding="utf-8-sig").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        row = _json.loads(line)
                        if isinstance(row, Mapping):
                            yield row
                return
            json_files = sorted(
                p
                for p in resolved.glob("*.json")
                if p.name.lower() not in {"dataset_info.json", "state.json"}
                and not p.name.startswith(".")
            )
            if json_files:
                import json as _json

                for jp in json_files:
                    raw = _json.loads(jp.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        for row in raw:
                            if isinstance(row, Mapping):
                                yield row
                    elif isinstance(raw, Mapping) and "data" in raw and isinstance(raw["data"], list):
                        for row in raw["data"]:
                            if isinstance(row, Mapping):
                                yield row
                return
            # Prefer train parquet when both train/test exist (avoid double-count).
            train_parquet = sorted(resolved.glob("**/train*.parquet"))
            parquet_files = train_parquet or sorted(resolved.glob("**/*.parquet"))
            # saved DatasetDict / Dataset directory
            if (resolved / "dataset_info.json").exists() or (resolved / "state.json").exists():
                ds_obj = load_from_disk(str(resolved))
                if hasattr(ds_obj, "keys") and subset in ds_obj:
                    ds = ds_obj[subset]
                elif hasattr(ds_obj, "keys") and "train" in ds_obj:
                    ds = ds_obj["train"]
                else:
                    ds = ds_obj
                for i in range(len(ds)):
                    yield ds[i]
                return
            subset_dir = resolved / subset
            if subset_dir.is_dir() and (
                (subset_dir / "dataset_info.json").exists() or (subset_dir / "state.json").exists()
            ):
                ds = load_from_disk(str(subset_dir))
                for i in range(len(ds)):
                    yield ds[i]
                return
            if parquet_files:
                ds = load_dataset(
                    "parquet",
                    data_files=[str(p) for p in parquet_files],
                    split="train",
                )
                for i in range(len(ds)):
                    yield ds[i]
                return

    # Hub: subset may be a HF config name (e.g. "articles") or a split alias.
    split_names = {"train", "test", "validation", "dev"}
    if subset and subset not in split_names:
        try:
            ds = load_dataset(dataset_id, subset, split="train")
        except Exception:
            ds = load_dataset(dataset_id, split="train")
    else:
        ds = load_dataset(dataset_id, split="train")
    for i in range(len(ds)):
        yield ds[i]


def iter_filtered_articles(
    *,
    dataset_id: str = LEGACY_LAW_DATASET,
    subset: str = LEGACY_LAW_SUBSET,
    max_rows: int = 500,
    categories: frozenset[str] = ALLOWED_CATEGORIES,
    rows: list[Mapping[str, Any]] | None = None,
) -> Iterator[ArticleRecord]:
    """Yield filtered ArticleRecords (legacy law path). Pass `rows` to avoid HF network (tests)."""
    emitted = 0
    limit = None if max_rows == 0 else max_rows

    if rows is not None:
        source_iter: Iterator[Mapping[str, Any]] = iter(rows)
    else:
        source_iter = _load_dataset_rows(dataset_id, subset)

    for row in source_iter:
        if not filter_article_row(row, categories=categories):
            continue
        yield row_to_record(row)
        emitted += 1
        if limit is not None and emitted >= limit:
            break


def iter_knowledge_chunks(
    *,
    source: str = "interview_zh",
    dataset_id: str = DEFAULT_DATASET,
    subset: str = DEFAULT_SUBSET,
    max_rows: int = 500,
    allowlist: list[str] | None = None,
    rows: list[Mapping[str, Any]] | None = None,
) -> Iterator[KnowledgeChunk]:
    """Yield KnowledgeChunks via CareerBot importers."""
    from lawbot.knowledge.importers import iter_source_chunks

    if rows is not None:
        source_iter: Iterator[Mapping[str, Any]] = iter(rows)
    else:
        source_iter = _load_dataset_rows(dataset_id, subset)
    yield from iter_source_chunks(
        source,
        source_iter,
        max_rows=max_rows,
        allowlist=allowlist,
    )
