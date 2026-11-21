"""Resume file storage on local disk (JWT-gated; not public static)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.resume_parse import parse_resume_file
from lawbot.db.models import UserResume

logger = logging.getLogger(__name__)

ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
}

EXT_FALLBACK: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
}


def resolve_resume_dir(settings: Settings, user_id: uuid.UUID) -> Path:
    path = Path(settings.resume_upload_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    dest = (path / str(user_id)).resolve()
    root = path.resolve()
    if not str(dest).startswith(str(root)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def resume_to_dict(row: UserResume) -> dict:
    structured = row.structured if isinstance(row.structured, dict) else {}
    skills = structured.get("skills") or []
    return {
        "id": str(row.id),
        "filename": row.filename,
        "mime": row.mime,
        "size_bytes": row.size_bytes,
        "parse_status": row.parse_status,
        "error": row.error,
        "is_active": row.is_active,
        "skills": skills if isinstance(skills, list) else [],
        "intent": structured.get("intent") or "",
        "structured": structured,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_active_resume(db: Session, user_id: uuid.UUID) -> UserResume | None:
    return db.scalars(
        select(UserResume)
        .where(UserResume.user_id == user_id, UserResume.is_active.is_(True))
        .order_by(UserResume.updated_at.desc())
        .limit(1)
    ).first()


async def save_and_parse_resume(
    db: Session,
    *,
    user_id: uuid.UUID,
    file: UploadFile,
    settings: Settings,
) -> UserResume:
    content_type = (file.content_type or "").lower().strip()
    original = file.filename or "resume"
    suffix = Path(original).suffix.lower()
    ext = ALLOWED_TYPES.get(content_type)
    if ext is None and suffix in EXT_FALLBACK:
        content_type = EXT_FALLBACK[suffix]
        ext = suffix
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported type; use PDF, DOCX, or PNG",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > settings.resume_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large; max {settings.resume_max_bytes} bytes",
        )

    user_dir = resolve_resume_dir(settings, user_id)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = user_dir / stored_name
    dest.write_bytes(data)
    rel_path = f"{user_id}/{stored_name}"

    db.execute(
        update(UserResume)
        .where(UserResume.user_id == user_id, UserResume.is_active.is_(True))
        .values(is_active=False)
    )

    row = UserResume(
        user_id=user_id,
        filename=Path(original).name[:255],
        storage_path=rel_path,
        mime=content_type,
        size_bytes=len(data),
        parse_status="parsing",
        structured={},
        is_active=True,
    )
    db.add(row)
    db.flush()

    result = parse_resume_file(dest, mime=content_type)
    row.parse_status = result.status
    row.raw_text = result.raw_text or None
    row.error = result.error
    if result.profile is not None:
        row.structured = result.profile.model_dump()
    else:
        row.structured = {}
    db.commit()
    db.refresh(row)
    return row


def delete_resume(db: Session, *, user_id: uuid.UUID, resume_id: uuid.UUID, settings: Settings) -> None:
    row = db.scalars(
        select(UserResume).where(UserResume.id == resume_id, UserResume.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    root = Path(settings.resume_upload_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    path = (root / row.storage_path).resolve()
    try:
        if path.is_file() and str(path).startswith(str(root.resolve())):
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete resume file %s: %s", path, exc)

    db.delete(row)
    db.commit()


def absolute_resume_path(settings: Settings, storage_path: str) -> Path:
    root = Path(settings.resume_upload_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    path = (root / storage_path).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    return path
