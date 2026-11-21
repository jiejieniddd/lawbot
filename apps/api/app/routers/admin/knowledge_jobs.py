from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_permission
from lawbot.db.models import KnowledgeImportJob, User
from lawbot.domain.schemas import ImportJobStatus, KnowledgeImportJobCreate, KnowledgeImportJobOut

router = APIRouter(prefix="/knowledge-import-jobs", tags=["admin-knowledge-jobs"])


@router.get("", response_model=list[KnowledgeImportJobOut])
def list_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge:read")),
) -> list[KnowledgeImportJob]:
    return list(
        db.scalars(select(KnowledgeImportJob).order_by(KnowledgeImportJob.created_at.desc())).all()
    )


@router.get("/{job_id}", response_model=KnowledgeImportJobOut)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge:read")),
) -> KnowledgeImportJob:
    job = db.get(KnowledgeImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


_CAREER_SOURCES = frozenset(
    {"interview_zh", "dev_docs_en", "hive_corpus", "cmmlu_cs", "ai_job_zh"}
)


@router.post("", response_model=KnowledgeImportJobOut, status_code=201)
def create_job(
    body: KnowledgeImportJobCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("knowledge:import")),
    settings: Settings = Depends(get_settings),
) -> KnowledgeImportJob:
    from lawbot.knowledge.importers import SOURCE_DEFAULT_DATASET, SOURCE_DOMAIN

    config = dict(body.config or {})
    # Prefer config.source; fall back to body.source when it looks like an importer id
    import_source = str(config.get("source") or "").strip()
    if not import_source and body.source in _CAREER_SOURCES:
        import_source = body.source
    if not import_source:
        import_source = "interview_zh"
    if import_source not in _CAREER_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported source={import_source!r}; expected one of {sorted(_CAREER_SOURCES)}",
        )
    config["source"] = import_source
    config.setdefault("dataset", SOURCE_DEFAULT_DATASET.get(import_source) or settings.hf_dataset_id)
    config.setdefault("subset", "train")
    config.setdefault("domain", SOURCE_DOMAIN.get(import_source))
    config.setdefault("max_rows", settings.import_max_rows)
    config.setdefault("allowlist", None)
    # Domain D must stay off the main search_kb index
    if import_source == "cmmlu_cs" and not config.get("memory_dir"):
        config["memory_dir"] = settings.rag_self_test_dir
    label = body.source if body.source and body.source not in _CAREER_SOURCES else f"career:{import_source}"
    job = KnowledgeImportJob(
        status=ImportJobStatus.PENDING,
        source=label,
        config=config,
        stats={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
