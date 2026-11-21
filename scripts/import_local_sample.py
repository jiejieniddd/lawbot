#!/usr/bin/env python3
"""Import a small HF / local sample into memory or Qdrant (no OpenSearch required)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.knowledge.embedding_settings import (  # noqa: E402
    EnvEmbeddingDefaults,
    require_litellm_ready,
    resolve_embedding_config,
)
from lawbot.knowledge.hf_import import DEFAULT_DATASET  # noqa: E402
from lawbot.knowledge.indexer import run_import  # noqa: E402
from lawbot.paths import resolve_rag_memory_dir  # noqa: E402
from lawbot.rag.factory import (  # noqa: E402
    RetrieverSettings,
    build_retriever,
    reset_memory_stores_for_tests,
)


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


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Low-spec sample knowledge import")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hub id or local path/parquet")
    parser.add_argument("--subset", default="articles")
    parser.add_argument("--max-rows", type=int, default=200)
    parser.add_argument("--backend", choices=("memory", "qdrant"), default="memory")
    parser.add_argument("--memory-dir", default="data/rag_memory")
    parser.add_argument(
        "--embedding-mode",
        default=None,
        choices=("fake", "litellm", "auto"),
        help="Override mode; default: Admin DB / EMBEDDING_MODE",
    )
    parser.add_argument("--embedding-model", default=None, help="Override EMBEDDING_MODEL")
    parser.add_argument("--embedding-api-key", default=None, help="Override EMBEDDING_API_KEY")
    parser.add_argument("--embedding-api-base", default=None, help="Override EMBEDDING_API_BASE")
    parser.add_argument("--embedding-dim", type=int, default=None, help="Override EMBEDDING_DIM")
    parser.add_argument("--recreate", action="store_true", help="Clear memory/qdrant before import")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--query", default="劳动合同", help="Smoke search query after import")
    args = parser.parse_args()

    memory_dir = str(resolve_rag_memory_dir(args.memory_dir))
    print(f"resolved memory_dir={memory_dir}")

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
        resolved = resolve_embedding_config(
            db,
            env,
            mode_override=args.embedding_mode,
        )
    finally:
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()

    emb_mode = resolved.effective_mode if resolved.mode == "auto" else resolved.mode
    print(
        f"embedding mode={resolved.mode} effective={emb_mode} "
        f"source={resolved.source} model={resolved.embedding_model or '(none)'} "
        f"dim={resolved.embedding_dim} api_key_configured={resolved.api_key_configured}"
    )
    if emb_mode == "fake" and (resolved.mode == "litellm" or args.embedding_mode == "litellm"):
        print(
            "ERROR: requested litellm but effective_mode=fake "
            "(missing embedding_model or API key / reuse_llm_provider)",
            file=sys.stderr,
        )
        return 1

    want_litellm = args.embedding_mode == "litellm" or resolved.mode == "litellm"
    if want_litellm:
        check = resolved
        if resolved.mode != "litellm":
            from lawbot.knowledge.embedding_settings import ResolvedEmbedding

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

    stats = run_import(
        max_rows=args.max_rows,
        dataset_id=args.dataset,
        subset=args.subset,
        index_backend=args.backend,
        memory_dir=memory_dir,
        embedding_mode=emb_mode,
        embedding_model=resolved.embedding_model,
        embedding_api_key=resolved.api_key,
        embedding_api_base=resolved.api_base,
        embedding_dim=resolved.embedding_dim,
        qdrant_url=args.qdrant_url,
        recreate=bool(args.recreate),
    )
    print("import stats:", stats)
    if int(stats.get("indexed") or 0) <= 0:
        print("ERROR: indexed == 0", file=sys.stderr)
        return 1

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
    hits = retriever.retrieve(args.query, top_k=3)
    print(f"sample search q={args.query!r} hits={len(hits)}")
    for h in hits:
        sid = h.citation.source_id
        print(f"  - {sid} | {h.citation.law_name} {h.citation.article_no}")
        if sid.startswith("fake-"):
            print("ERROR: fake source_id in real retrieval path", file=sys.stderr)
            return 1
    if not hits:
        print("NOTE: no hits for smoke query (index may lack matching terms); indexed>0 still OK")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
