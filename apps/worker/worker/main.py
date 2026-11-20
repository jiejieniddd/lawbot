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

    from lawbot.llm.client import resolve_embedding_credentials

    settings = get_worker_settings()
    cfg = job.config or {}
    max_rows = int(cfg.get("max_rows", settings.import_max_rows))
    recreate = bool(cfg.get("recreate", False))
    dataset_id = str(cfg.get("dataset", settings.hf_dataset_id))
    subset = str(cfg.get("subset", "articles"))
    index_backend = str(cfg.get("index_backend", settings.index_backend)).lower()
    memory_dir = str(cfg.get("memory_dir", settings.rag_memory_dir))

    embedding_api_key = settings.embedding_api_key
    embedding_api_base = settings.embedding_api_base
    engine = create_engine(settings.database_url)
    db = Session(engine)
    try:
        emb = resolve_embedding_credentials(
            db,
            embedding_api_key=embedding_api_key,
            embedding_api_base=embedding_api_base,
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.jwt_secret,
        )
        if emb is not None:
            embedding_api_key = emb.api_key
            embedding_api_base = emb.api_base
            logger.info("embedding credentials source=%s", emb.source)
        elif settings.embedding_mode == "litellm":
            raise RuntimeError(
                "EMBEDDING_MODE=litellm but no EMBEDDING_API_KEY and no enabled llm_providers"
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
        settings.embedding_mode,
    )
    try:
        stats = run_import(
            max_rows=max_rows,
            dataset_id=dataset_id,
            subset=subset,
            qdrant_url=settings.qdrant_url,
            opensearch_url=settings.opensearch_url,
            collection=settings.qdrant_collection,
            index=settings.opensearch_index,
            embedding_model=settings.embedding_model,
            embedding_api_key=embedding_api_key,
            embedding_api_base=embedding_api_base,
            embedding_dim=settings.embedding_dim,
            embedding_mode=settings.embedding_mode,
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
