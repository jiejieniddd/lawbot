"""Domain D self-test quiz — isolated from main search_kb RRF."""

from __future__ import annotations

import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import get_current_user, get_db
from lawbot.db.models import User

router = APIRouter(tags=["self-quiz"])


class SelfQuizRequest(BaseModel):
    topic: str | None = None
    seed: int | None = None


class SelfQuizOption(BaseModel):
    key: str
    text: str


class SelfQuizResponse(BaseModel):
    question_id: str
    question: str
    options: list[SelfQuizOption] = Field(default_factory=list)
    topic: str | None = None
    answer_key: str | None = None
    explanation: str | None = None


def _load_self_test_records(memory_dir: str) -> list[dict]:
    path = Path(memory_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    records_path = path / "records.jsonl"
    if not records_path.is_file():
        return []
    out: list[dict] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json

            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("domain") or "") != "self_test":
            # Still allow if stored without domain but under self_test dir
            pass
        out.append(row)
    return out


def _options_from_record(row: dict) -> tuple[list[SelfQuizOption], str | None]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    raw_opts = meta.get("options") or row.get("options")
    answer_key = meta.get("answer_key") or row.get("answer_key")
    options: list[SelfQuizOption] = []
    if isinstance(raw_opts, list):
        for i, item in enumerate(raw_opts):
            if isinstance(item, dict):
                key = str(item.get("key") or chr(ord("A") + i))
                text = str(item.get("text") or item.get("value") or "")
            else:
                key = chr(ord("A") + i)
                text = str(item)
            if text:
                options.append(SelfQuizOption(key=key, text=text))
    if not options:
        # Fallback: parse A/B/C/D lines from text
        import re

        text = str(row.get("text") or row.get("chunk_text") or "")
        for m in re.finditer(r"^([A-D])[\.\:\、\)]\s*(.+)$", text, re.M):
            options.append(SelfQuizOption(key=m.group(1), text=m.group(2).strip()))
    return options, str(answer_key) if answer_key else None


@router.post("/self-quiz", response_model=SelfQuizResponse)
def self_quiz(
    body: SelfQuizRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = db, user
    settings = get_settings()
    records = _load_self_test_records(settings.rag_self_test_dir)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="self_test index empty; import cmmlu_cs first",
        )
    topic = (body.topic or "").strip().lower()
    pool = records
    if topic:
        filtered = [
            r
            for r in records
            if topic in str(r.get("category") or "").lower()
            or topic in str(r.get("title") or "").lower()
            or topic in " ".join(r.get("skills") or []).lower()
        ]
        if filtered:
            pool = filtered
    rng = random.Random(body.seed if body.seed is not None else None)
    row = rng.choice(pool)
    options, answer_key = _options_from_record(row)
    question = str(row.get("title") or "").strip()
    if not question:
        question = str(row.get("text") or "")[:300]
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return SelfQuizResponse(
        question_id=str(row.get("source_id") or ""),
        question=question,
        options=options,
        topic=str(row.get("category") or meta.get("subject") or None),
        answer_key=answer_key,
        explanation=str(meta.get("explanation") or "") or None,
    )
