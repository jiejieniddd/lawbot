from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import get_current_user, get_db
from app.services.resumes import (
    absolute_resume_path,
    delete_resume,
    get_active_resume,
    resume_to_dict,
    save_and_parse_resume,
)
from lawbot.db.models import User

router = APIRouter(prefix="/me/resumes", tags=["resumes"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    row = await save_and_parse_resume(db, user_id=user.id, file=file, settings=settings)
    return resume_to_dict(row)


@router.get("/active")
def get_active(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = get_active_resume(db, user.id)
    if row is None:
        return {"resume": None}
    return {"resume": resume_to_dict(row)}


@router.get("/{resume_id}/file")
def download_resume_file(
    resume_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import select

    from lawbot.db.models import UserResume

    settings = get_settings()
    row = db.scalars(
        select(UserResume).where(UserResume.id == resume_id, UserResume.user_id == user.id)
    ).first()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Resume not found")
    path = absolute_resume_path(settings, row.storage_path)
    if not path.is_file():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, filename=row.filename, media_type=row.mime or "application/octet-stream")


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_resume(
    resume_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    delete_resume(db, user_id=user.id, resume_id=resume_id, settings=settings)
    return None
