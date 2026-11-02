from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db, require_admin
from lawbot.db.models import KnowledgeDocument, User
from lawbot.domain.schemas import KnowledgeCreate, KnowledgeOut, KnowledgePatch

router = APIRouter(prefix="/knowledge/documents", tags=["admin-knowledge"])


@router.get("", response_model=list[KnowledgeOut])
def list_docs(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[KnowledgeDocument]:
    return list(db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())).all())


@router.post("", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
def create_doc(
    body: KnowledgeCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        title=body.title,
        doc_type=body.doc_type,
        status=body.status,
        summary=body.summary,
        source_uri=body.source_uri,
        meta=body.meta,
        created_by=admin.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.patch("/{doc_id}", response_model=KnowledgeOut)
def patch_doc(
    doc_id: UUID,
    body: KnowledgePatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> KnowledgeDocument:
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(doc, k, v.value if hasattr(v, "value") else v)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_doc(
    doc_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    db.delete(doc)
    db.commit()
