"""Avatar file storage on local disk.

Future: swap to OSS/MinIO behind the same save/delete interface.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import Settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def resolve_upload_dir(settings: Settings) -> Path:
    path = Path(settings.upload_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def uploads_static_root(settings: Settings) -> Path:
    """Parent of UPLOAD_DIR (e.g. data/uploads), mounted at /uploads."""
    return resolve_upload_dir(settings).parent


def public_avatar_url(filename: str) -> str:
    return f"/uploads/avatars/{filename}"


async def save_avatar(user_id: uuid.UUID, file: UploadFile, settings: Settings) -> str:
    content_type = (file.content_type or "").lower().strip()
    ext = ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image type; use jpeg, png, or webp",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > settings.avatar_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large; max {settings.avatar_max_bytes} bytes",
        )

    upload_dir = resolve_upload_dir(settings)
    filename = f"{user_id}_{uuid.uuid4().hex}{ext}"
    dest = upload_dir / filename
    # Guard against path traversal (filename is fully generated)
    if dest.resolve().parent != upload_dir:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")
    dest.write_bytes(data)
    return public_avatar_url(filename)


def delete_avatar_file(avatar_url: str | None, settings: Settings) -> None:
    if not avatar_url:
        return
    prefix = "/uploads/avatars/"
    if not avatar_url.startswith(prefix):
        return
    name = avatar_url[len(prefix) :]
    if not name or "/" in name or "\\" in name or ".." in name:
        return
    upload_dir = resolve_upload_dir(settings)
    path = (upload_dir / name).resolve()
    try:
        if path.parent != upload_dir or not path.is_file():
            return
        path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete avatar file %s: %s", path, exc)
