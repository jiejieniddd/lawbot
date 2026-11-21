from __future__ import annotations

import logging
import time

from sqlalchemy import select

from lawbot.db.models import KnowledgeImportJob
from lawbot.db.session import get_sessionmaker
from lawbot.domain.schemas import ImportJobStatus
from lawbot.knowledge.indexer import run_import
from worker.settings import get_worker_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("lawbot.worker")


def claim_next_job(database_url: str) -> KnowledgeImportJob | None:
    factory = get_sessionmaker(database_url)
    db = factory()
    try:
        job = db.scalar(
            select(KnowledgeImportJob)
            .where(KnowledgeImportJob.status == ImportJobStatus.PENDING)
            .order_by(KnowledgeImportJob.created_at.asc())
            .limit(1)
        )
        if job is None:
            return None
        job.status = ImportJobStatus.RUNNING
        job.error = None
        db.commit()
        db.refresh(job)
        # detach fields
        db.expunge(job)
        return job
    finally:
        db.close()


def finish_job(database_url: str, job_id, *, status: str, stats: dict | None = None, error: str | None = None) -> None:
    factory = get_sessionmaker(database_url)
    db = factory()
    try:
        job = db.get(KnowledgeImportJob, job_id)
        if job is None:
            return
        job.status = status
        if stats is not None:
            job.stats = stats
        job.error = error
        db.commit()
    finally:
        db.close()


def process_job(job: KnowledgeImportJob) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from lawbot.knowledge.embedding_settings import (
        EnvEmbeddingDefaults,
        require_litellm_ready,
        resolve_embedding_config,
    )

    settings = get_worker_settings()
    cfg = job.config or {}
    max_rows = int(cfg.get("max_rows", settings.import_max_rows))
    recreate = bool(cfg.get("recreate", False))
    dataset_id = str(cfg.get("dataset", settings.hf_dataset_id))
    subset = str(cfg.get("subset", "train"))
    import_source = str(cfg.get("source", "interview_zh"))
    domain = cfg.get("domain")
    allowlist = cfg.get("allowlist")
    if isinstance(allowlist, str):
        allowlist = [x.strip() for x in allowlist.split(",") if x.strip()]
    index_backend = str(cfg.get("index_backend", settings.index_backend)).lower()
    from lawbot.paths import resolve_rag_memory_dir

    # Domain D (cmmlu_cs / self_test) defaults to isolated dir — never main search_kb.
    default_memory = settings.rag_memory_dir
    if import_source == "cmmlu_cs" and not cfg.get("memory_dir"):
        default_memory = settings.rag_self_test_dir
    memory_dir = str(resolve_rag_memory_dir(cfg.get("memory_dir", default_memory)))

    engine = create_engine(settings.database_url)
    db = Session(engine)
    try:
        resolved = resolve_embedding_config(
            db,
            EnvEmbeddingDefaults(
                mode=settings.embedding_mode,
                embedding_model=settings.embedding_model,
                api_key=settings.embedding_api_key,
                api_base=settings.embedding_api_base,
                embedding_dim=settings.embedding_dim,
                encryption_key=settings.encryption_key or None,
                jwt_secret=settings.jwt_secret,
            ),
        )
        emb_mode = resolved.effective_mode if resolved.mode == "auto" else resolved.mode
        if resolved.mode == "litellm":
            err = require_litellm_ready(resolved)
            if err:
                raise RuntimeError(err)
        logger.info(
            "embedding source=%s mode=%s effective=%s model=%s",
            resolved.source,
            resolved.mode,
            emb_mode,
            resolved.embedding_model or "(none)",
        )
    finally:
        db.close()
        engine.dispose()

    logger.info(
        "processing job=%s max_rows=%s dataset=%s backend=%s embedding_mode=%s",
        job.id,
        max_rows,
        dataset_id,
        index_backend,
        emb_mode,
    )
    try:
        stats = run_import(
            max_rows=max_rows,
            dataset_id=dataset_id,
            subset=subset,
            source=import_source,
            domain=str(domain) if domain else None,
            allowlist=allowlist if isinstance(allowlist, list) else None,
            qdrant_url=settings.qdrant_url,
            opensearch_url=settings.opensearch_url,
            collection=settings.qdrant_collection,
            index=settings.opensearch_index,
            embedding_model=resolved.embedding_model,
            embedding_api_key=resolved.api_key,
            embedding_api_base=resolved.api_base,
            embedding_dim=resolved.embedding_dim,
            embedding_mode=emb_mode,
            recreate=recreate,
            index_backend=index_backend,
            memory_dir=memory_dir,
        )
        finish_job(settings.database_url, job.id, status=ImportJobStatus.SUCCEEDED, stats=stats)
        logger.info("job=%s succeeded stats=%s", job.id, stats)
    except Exception as exc:
        logger.exception("job=%s failed", job.id)
        finish_job(
            settings.database_url,
            job.id,
            status=ImportJobStatus.FAILED,
            stats={"indexed": 0},
            error=str(exc),
        )


def loop_forever() -> None:
    settings = get_worker_settings()
    logger.info("worker started poll=%ss", settings.worker_poll_seconds)
    while True:
        job = claim_next_job(settings.database_url)
        if job is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        process_job(job)


def main() -> None:
    loop_forever()


if __name__ == "__main__":
    main()
