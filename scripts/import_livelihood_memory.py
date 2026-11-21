#!/usr/bin/env python3
"""Offline livelihood allowlist re-import into memory/qdrant (does not change product APIs).

Filters HF/local articles by title allowlist + denylist, then writes with --recreate.
--max-rows is a post-filter cap (not "first N rows of the raw dataset").
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.knowledge.embedding_settings import (  # noqa: E402
    EnvEmbeddingDefaults,
    ResolvedEmbedding,
    require_litellm_ready,
    resolve_embedding_config,
)
from lawbot.knowledge.hf_import import (  # noqa: E402
    ALLOWED_CATEGORIES,
    DEFAULT_DATASET,
    _load_dataset_rows,
    filter_article_row,
)
from lawbot.knowledge.indexer import run_import  # noqa: E402
from lawbot.paths import resolve_rag_memory_dir  # noqa: E402
from lawbot.rag.factory import (  # noqa: E402
    RetrieverSettings,
    build_retriever,
    reset_memory_stores_for_tests,
)

DEFAULT_ALLOWLIST = ROOT / "scripts" / "livelihood_law_allowlist.txt"
DEFAULT_DENYLIST = ROOT / "scripts" / "livelihood_law_denylist.txt"

DEFAULT_SMOKE_QUERIES = (
    "别人欠我钱不还",
    "劳动合同",
    "试用期辞退",
    "追尾",
    "交通事故",
)

_WS_RE = re.compile(r"\s+")


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _open_db():
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None, None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
    except ImportError:
        return None, None
    engine = create_engine(url)
    return engine, Session(engine)


def _norm_title(title: str) -> str:
    return _WS_RE.sub("", (title or "")).casefold()


def _load_substring_list(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"list file not found: {path}")
    items: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(_norm_title(line))
    return items


def _title_allowed(title: str, allow: list[str], deny: list[str]) -> bool:
    norm = _norm_title(title)
    if not norm:
        return False
    if deny and any(d and d in norm for d in deny):
        return False
    if not allow:
        return False
    return any(a and a in norm for a in allow)


def _collect_matched_rows(
    *,
    dataset_id: str,
    subset: str,
    allow: list[str],
    deny: list[str],
    max_rows: int,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    limit = None if max_rows == 0 else max_rows
    for row in _load_dataset_rows(dataset_id, subset):
        if not filter_article_row(row, categories=ALLOWED_CATEGORIES):
            continue
        title = str(row.get("title") or "")
        if not _title_allowed(title, allow, deny):
            continue
        matched.append(dict(row))
        if limit is not None and len(matched) >= limit:
            break
    return matched


def _print_stats(rows: Iterable[Mapping[str, Any]], *, top_n: int = 15) -> None:
    rows_list = list(rows)
    cat = Counter(str(r.get("category") or "(空)") for r in rows_list)
    laws = Counter(str(r.get("title") or "(无标题)") for r in rows_list)
    print(f"matched_rows={len(rows_list)}")
    print("category_counts:")
    for name, n in cat.most_common():
        pct = 100.0 * n / max(1, len(rows_list))
        print(f"  {name}: {n} ({pct:.1f}%)")
    print(f"top_law_name (top {top_n}):")
    for name, n in laws.most_common(top_n):
        print(f"  {n:5d}  {name}")


def _resolve_embedding(args: argparse.Namespace):
    env = EnvEmbeddingDefaults(
        mode=os.environ.get("EMBEDDING_MODE", "auto"),
        embedding_model=args.embedding_model
        if args.embedding_model is not None
        else os.environ.get("EMBEDDING_MODEL", ""),
        api_key=args.embedding_api_key
        if args.embedding_api_key is not None
        else os.environ.get("EMBEDDING_API_KEY", ""),
        api_base=args.embedding_api_base
        if args.embedding_api_base is not None
        else (os.environ.get("EMBEDDING_API_BASE") or None),
        embedding_dim=args.embedding_dim
        if args.embedding_dim is not None
        else int(os.environ.get("EMBEDDING_DIM") or 384),
        encryption_key=os.environ.get("ENCRYPTION_KEY") or None,
        jwt_secret=os.environ.get("SECRET_KEY")
        or os.environ.get("JWT_SECRET")
        or "dev-secret-change-me",
    )
    engine, db = _open_db()
    try:
        resolved = resolve_embedding_config(db, env, mode_override=args.embedding_mode)
    finally:
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()
    return resolved


def main() -> int:
    _load_dotenv()
    default_dataset = (os.environ.get("HF_DATASET_ID") or "").strip() or DEFAULT_DATASET

    parser = argparse.ArgumentParser(
        description="Livelihood allowlist offline re-import (memory/qdrant); not a product API"
    )
    parser.add_argument("--dataset", default=default_dataset, help="Hub id or local path/parquet")
    parser.add_argument("--subset", default="articles")
    parser.add_argument(
        "--allowlist",
        default=str(DEFAULT_ALLOWLIST),
        help="UTF-8 title substring allowlist (one per line)",
    )
    parser.add_argument(
        "--denylist",
        default=str(DEFAULT_DENYLIST),
        help="UTF-8 title substring denylist (deny wins)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=12000,
        help="Post-filter write cap; 0 = no truncation after filter",
    )
    parser.add_argument("--backend", choices=("memory", "qdrant"), default="memory")
    parser.add_argument("--memory-dir", default="data/rag_memory")
    parser.add_argument(
        "--embedding-mode",
        default=None,
        choices=("fake", "litellm", "auto"),
        help="Override mode; default Admin DB / EMBEDDING_MODE. Use fake only if explicit.",
    )
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-api-key", default=None)
    parser.add_argument("--embedding-api-base", default=None)
    parser.add_argument("--embedding-dim", type=int, default=None)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Required for import: clear memory/qdrant before write",
    )
    parser.add_argument("--preview-only", action="store_true", help="Stats only; no embed/write")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument(
        "--query",
        action="append",
        default=None,
        help="Smoke query (repeatable). Default: built-in livelihood queries",
    )
    args = parser.parse_args()

    allow_path = Path(args.allowlist)
    if not allow_path.is_absolute():
        allow_path = (ROOT / allow_path).resolve()
    deny_path = Path(args.denylist)
    if not deny_path.is_absolute():
        deny_path = (ROOT / deny_path).resolve()

    try:
        allow = _load_substring_list(allow_path)
        deny = _load_substring_list(deny_path) if deny_path.is_file() else []
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not allow:
        print("ERROR: allowlist is empty", file=sys.stderr)
        return 1

    print(f"dataset={args.dataset!r} subset={args.subset}")
    print(f"allowlist={allow_path} ({len(allow)} patterns) denylist={deny_path} ({len(deny)} patterns)")
    print(f"max_rows={args.max_rows} (post-filter cap; 0=unlimited)")

    print("scanning dataset (this may take a while)…")
    matched = _collect_matched_rows(
        dataset_id=args.dataset,
        subset=args.subset,
        allow=allow,
        deny=deny,
        max_rows=args.max_rows,
    )
    if not matched:
        print(
            "ERROR: 白名单过滤后 0 条。请放宽 allowlist 或检查 dataset / status=有效。",
            file=sys.stderr,
        )
        return 1

    _print_stats(matched)

    if args.preview_only:
        print("preview-only: skip write/embedding")
        print("OK")
        return 0

    if not args.recreate:
        print(
            "ERROR: 民生重导必须带 --recreate，以免与旧索引混杂。预览请用 --preview-only。",
            file=sys.stderr,
        )
        return 1

    memory_dir = str(resolve_rag_memory_dir(args.memory_dir))
    print(f"resolved memory_dir={memory_dir}")

    resolved = _resolve_embedding(args)
    emb_mode = resolved.effective_mode if resolved.mode == "auto" else resolved.mode
    print(
        f"embedding mode={resolved.mode} effective={emb_mode} "
        f"source={resolved.source} model={resolved.embedding_model or '(none)'} "
        f"dim={resolved.embedding_dim} api_key_configured={resolved.api_key_configured}"
    )

    # Refuse silent fake unless user explicitly asked for fake.
    if emb_mode == "fake" and args.embedding_mode != "fake":
        print(
            "ERROR: effective_mode=fake but --embedding-mode fake 未显式指定；"
            "请配置 Admin Embedding / litellm，或显式传入 --embedding-mode fake。",
            file=sys.stderr,
        )
        return 1

    if emb_mode == "fake" and (resolved.mode == "litellm" or args.embedding_mode == "litellm"):
        print(
            "ERROR: requested litellm but effective_mode=fake "
            "(missing embedding_model or API key / reuse_llm_provider)",
            file=sys.stderr,
        )
        return 1

    want_litellm = args.embedding_mode == "litellm" or resolved.mode == "litellm" or (
        args.embedding_mode is None and emb_mode == "litellm"
    )
    if want_litellm and emb_mode != "fake":
        check = resolved
        if resolved.mode != "litellm":
            check = ResolvedEmbedding(
                mode="litellm",
                embedding_model=resolved.embedding_model,
                api_key=resolved.api_key,
                api_base=resolved.api_base,
                embedding_dim=resolved.embedding_dim,
                reuse_llm_provider=resolved.reuse_llm_provider,
                api_key_configured=resolved.api_key_configured,
                source=resolved.source,
                effective_mode="litellm",
                api_key_unreadable=resolved.api_key_unreadable,
            )
        err = require_litellm_ready(check)
        if err:
            print(f"ERROR: {err}", file=sys.stderr)
            return 1
        emb_mode = "litellm"

    if args.backend == "memory":
        reset_memory_stores_for_tests()

    # rows already filtered+capped; max_rows=0 so indexer does not re-truncate by HF order.
    stats = run_import(
        max_rows=0,
        dataset_id=args.dataset,
        subset=args.subset,
        index_backend=args.backend,
        memory_dir=memory_dir,
        embedding_mode=emb_mode,
        embedding_model=resolved.embedding_model,
        embedding_api_key=resolved.api_key or "",
        embedding_api_base=resolved.api_base,
        embedding_dim=resolved.embedding_dim,
        qdrant_url=args.qdrant_url,
        recreate=True,
        rows=matched,
    )
    print("import stats:", stats)
    if int(stats.get("indexed") or 0) <= 0:
        print("ERROR: indexed == 0", file=sys.stderr)
        return 1

    print("post-import distribution (from matched filter set):")
    _print_stats(matched)

    reset_memory_stores_for_tests()
    mode = "memory" if args.backend == "memory" else "hybrid"
    retriever = build_retriever(
        RetrieverSettings(
            mode=mode,
            embedding_mode=emb_mode,
            embedding_model=resolved.embedding_model,
            embedding_api_key=resolved.api_key,
            embedding_api_base=resolved.api_base,
            embedding_dim=resolved.embedding_dim,
            memory_dir=memory_dir,
            qdrant_url=args.qdrant_url,
        )
    )
    queries = args.query if args.query else list(DEFAULT_SMOKE_QUERIES)
    for q in queries:
        hits = retriever.retrieve(q, top_k=3)
        print(f"sample search q={q!r} hits={len(hits)}")
        for h in hits:
            sid = h.citation.source_id
            print(f"  - {sid} | {h.citation.law_name} {h.citation.article_no}")
            if sid.startswith("fake-") and emb_mode != "fake":
                print("ERROR: fake source_id in real retrieval path", file=sys.stderr)
                return 1
        if not hits:
            print("NOTE: no hits for this smoke query")

    print("OK — 请重启 API 以加载新的 memory 索引")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
