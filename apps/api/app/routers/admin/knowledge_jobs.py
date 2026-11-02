from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_admin
from lawbot.db.models import KnowledgeImportJob, User
from lawbot.domain.schemas import ImportJobStatus, KnowledgeImportJobCreate, KnowledgeImportJobOut

router = APIRouter(prefix="/knowledge-import-jobs", tags=["admin-knowledge-jobs"])


@router.get("", response_model=list[KnowledgeImportJobOut])
def list_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[KnowledgeImportJob]:
    return list(
        db.scalars(select(KnowledgeImportJob).order_by(KnowledgeImportJob.created_at.desc())).all()
    )


@router.get("/{job_id}", response_model=KnowledgeImportJobOut)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> KnowledgeImportJob:
    job = db.get(KnowledgeImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=KnowledgeImportJobOut, status_code=201)
def create_job(
    body: KnowledgeImportJobCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> KnowledgeImportJob:
    config = dict(body.config or {})
    config.setdefault("dataset", settings.hf_dataset_id)
    config.setdefault("subset", "articles")
    config.setdefault("status", "有效")
    config.setdefault("categories", ["法律", "行政法规", "司法解释"])
    config.setdefault("max_rows", settings.import_max_rows)
    source = body.source or "hf:china-effective-laws-regulations"
    job = KnowledgeImportJob(
        status=ImportJobStatus.PENDING,
        source=source,
        config=config,
        stats={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
