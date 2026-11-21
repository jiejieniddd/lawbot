"""JD file storage (JWT-gated; reuse resume parse pipeline)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.services.resume_parse import parse_resume_file
from lawbot.db.models import UserJd
from lawbot.knowledge.importers.ai_job_zh import _extract_skills

logger = logging.getLogger(__name__)

ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "text/plain": ".txt",
}

EXT_FALLBACK: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".txt": "text/plain",
}


def resolve_jd_dir(settings: Settings, user_id: uuid.UUID) -> Path:
    path = Path(settings.jd_upload_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    dest = (path / str(user_id)).resolve()
    root = path.resolve()
    if not str(dest).startswith(str(root)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def jd_to_dict(row: UserJd) -> dict:
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
        "raw_text": (row.raw_text or "")[:8000],
        "text": (row.raw_text or "")[:8000],
        "structured": structured,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_active_jd(db: Session, user_id: uuid.UUID) -> UserJd | None:
    return db.scalars(
        select(UserJd)
        .where(UserJd.user_id == user_id, UserJd.is_active.is_(True))
        .order_by(UserJd.updated_at.desc())
        .limit(1)
    ).first()


def _parse_jd_file(path: Path, *, mime: str) -> tuple[str, str, dict, str | None]:
    """Returns status, raw_text, structured, error."""
    suffix = path.suffix.lower()
    if suffix == ".txt" or mime == "text/plain":
        raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not raw:
            return "failed_text", "", {}, "Empty text file"
        skills = _extract_skills(raw)
        return "ready", raw, {"skills": skills, "title": raw.splitlines()[0][:80]}, None
    result = parse_resume_file(path, mime=mime)
    if result.status != "ready":
        return result.status, result.raw_text or "", {}, result.error
    skills = _extract_skills(result.raw_text or "")
    title = (result.raw_text or "").splitlines()[0][:80] if result.raw_text else ""
    return "ready", result.raw_text or "", {"skills": skills, "title": title}, None


async def save_and_parse_jd(
    db: Session,
    *,
    user_id: uuid.UUID,
    file: UploadFile,
    settings: Settings,
) -> UserJd:
    content_type = (file.content_type or "").lower().strip()
    original = file.filename or "jd"
    suffix = Path(original).suffix.lower()
    ext = ALLOWED_TYPES.get(content_type)
    if ext is None and suffix in EXT_FALLBACK:
        content_type = EXT_FALLBACK[suffix]
        ext = suffix
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported type; use PDF, DOCX, PNG, or TXT",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > settings.jd_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large; max {settings.jd_max_bytes} bytes",
        )

    user_dir = resolve_jd_dir(settings, user_id)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = user_dir / stored_name
    dest.write_bytes(data)
    rel_path = f"{user_id}/{stored_name}"

    db.execute(
        update(UserJd)
        .where(UserJd.user_id == user_id, UserJd.is_active.is_(True))
        .values(is_active=False)
    )

    row = UserJd(
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

    status_s, raw, structured, err = _parse_jd_file(dest, mime=content_type)
    row.parse_status = status_s
    row.raw_text = raw or None
    row.structured = structured
    row.error = err
    db.commit()
    db.refresh(row)
    return row


def delete_jd(db: Session, *, user_id: uuid.UUID, jd_id: uuid.UUID, settings: Settings) -> None:
    row = db.scalars(select(UserJd).where(UserJd.id == jd_id, UserJd.user_id == user_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="JD not found")
    root = Path(settings.jd_upload_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    path = (root / row.storage_path).resolve()
    try:
        if path.is_file() and str(path).startswith(str(root.resolve())):
            path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete JD file %s: %s", path, exc)
    db.delete(row)
    db.commit()
