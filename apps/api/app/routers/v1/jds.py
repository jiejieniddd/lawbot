from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import get_current_user, get_db
from app.services.jds import delete_jd, get_active_jd, jd_to_dict, resolve_jd_dir, save_and_parse_jd
from lawbot.db.models import User, UserJd
from lawbot.knowledge.importers.ai_job_zh import _extract_skills

router = APIRouter(prefix="/me/jds", tags=["jds"])


class JdPasteBody(BaseModel):
    text: str = Field(min_length=20, max_length=50_000)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_jd(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    row = await save_and_parse_jd(db, user_id=user.id, file=file, settings=settings)
    return jd_to_dict(row)


@router.post("/paste", status_code=status.HTTP_201_CREATED)
def paste_jd(
    body: JdPasteBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    text = body.text.strip()
    skills = _extract_skills(text)
    db.execute(
        update(UserJd)
        .where(UserJd.user_id == user.id, UserJd.is_active.is_(True))
        .values(is_active=False)
    )
    row = UserJd(
        user_id=user.id,
        filename="pasted.txt",
        storage_path=f"{user.id}/pasted-{uuid.uuid4().hex}.txt",
        mime="text/plain",
        size_bytes=len(text.encode("utf-8")),
        parse_status="ready",
        raw_text=text,
        structured={"skills": skills, "title": text.splitlines()[0][:80]},
        is_active=True,
    )
    # Persist paste text under upload dir for audit (optional disk write)
    settings = get_settings()
    dest_dir = resolve_jd_dir(settings, user.id)
    dest = dest_dir / Path(row.storage_path).name
    dest.write_text(text, encoding="utf-8")
    db.add(row)
    db.commit()
    db.refresh(row)
    return jd_to_dict(row)


@router.get("/active")
def get_active(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = get_active_jd(db, user.id)
    if row is None:
        return {"jd": None}
    return {"jd": jd_to_dict(row)}


@router.delete("/{jd_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_jd(
    jd_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    delete_jd(db, user_id=user.id, jd_id=jd_id, settings=settings)
    return None
