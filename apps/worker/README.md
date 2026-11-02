# LawBot worker

Polls `knowledge_import_jobs` (`pending` → `running` → `succeeded|failed`), loads HF articles, and upserts into Qdrant + OpenSearch.

```bash
# from repo root
uv sync --all-packages
uv run --package lawbot-worker lawbot-worker
# or
cd apps/worker && uv run python -m worker.main
```

Env: `DATABASE_URL`, `IMPORT_MAX_ROWS`, `QDRANT_URL`, `OPENSEARCH_URL`, `EMBEDDING_*`, `HF_DATASET_ID`.
