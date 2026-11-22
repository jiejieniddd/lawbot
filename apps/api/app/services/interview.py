"""Mock interview session orchestration (CareerBot)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.services.resumes import get_active_resume, resume_to_dict
from lawbot.knowledge.importers.ai_job_zh import _extract_skills
from lawbot.agent.citations import strip_internal_ids
from lawbot.agent.interview.runner import (
    build_questions,
    next_question,
    score_turn,
    summarize_report,
)
from lawbot.db.models import InterviewSession, InterviewTurn
from lawbot.llm.client import ProviderCredentials

logger = logging.getLogger(__name__)

DISCLAIMER = "AI 初评仅供参考，不构成录用承诺或官方认证。"


def _turn_public(turn: InterviewTurn, *, include_feedback: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(turn.id),
        "seq": turn.seq,
        "question": strip_internal_ids(turn.question or ""),
        "answered": bool((turn.answer or "").strip()),
    }
    if include_feedback and turn.answer is not None:
        data["answer"] = turn.answer
        if turn.score is not None:
            data["score"] = turn.score
        if turn.feedback:
            data["feedback"] = strip_internal_ids(turn.feedback)
        if turn.dimensions:
            data["dimensions"] = turn.dimensions
    return data


def session_public(
    session: InterviewSession,
    *,
    include_report: bool = False,
) -> dict[str, Any]:
    turns = sorted(session.turns or [], key=lambda t: t.seq)
    answered = sum(1 for t in turns if (t.answer or "").strip())
    current = next((t for t in turns if not (t.answer or "").strip()), None)
    body: dict[str, Any] = {
        "id": str(session.id),
        "status": session.status,
        "question_count": session.question_count,
        "target_role": session.target_role or "",
        "answered_count": answered,
        "current_seq": current.seq if current else None,
        "current_question": _turn_public(current, include_feedback=False) if current else None,
        "turns": [_turn_public(t) for t in turns if (t.answer or "").strip() or t is current],
    }
    if include_report and session.report:
        body["report"] = session.report
    return body


def get_session_for_user(
    db: Session, session_id: uuid.UUID, user_id: uuid.UUID
) -> InterviewSession:
    row = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.id == session_id, InterviewSession.user_id == user_id)
        .options(selectinload(InterviewSession.turns))
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="面试场次不存在")
    return row


def _jd_snapshot_from_text(jd_text: str) -> dict[str, Any]:
    text = (jd_text or "").strip()
    if not text:
        return {}
    skills = _extract_skills(text)
    title = text.splitlines()[0][:80] if text.splitlines() else text[:80]
    return {
        "parse_status": "ready",
        "raw_text": text[:8000],
        "text": text[:8000],
        "skills": skills if isinstance(skills, list) else [],
        "structured": {"skills": skills if isinstance(skills, list) else [], "title": title},
        "filename": "session-paste.txt",
    }


def create_session(
    db: Session,
    *,
    user_id: uuid.UUID,
    question_count: int,
    target_role: str,
    jd_text: str = "",
    retriever: Any | None,
) -> InterviewSession:
    if question_count not in (5, 8):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="题量仅支持 5 或 8",
        )
    resume = get_active_resume(db, user_id)
    resume_snap: dict[str, Any] = {}
    resume_id = None
    if resume is not None and resume.parse_status == "ready":
        resume_snap = resume_to_dict(resume)
        resume_id = resume.id

    # Job info is per-session (prep form), not from settings / user_jds.
    jd_snap = _jd_snapshot_from_text(jd_text)
    role = (target_role or "").strip()
    if not role:
        role = str((jd_snap.get("structured") or {}).get("title") or "")
    if not role and jd_snap.get("raw_text"):
        role = str(jd_snap["raw_text"]).strip().splitlines()[0][:40]

    # Resume optional; require target role or pasted JD for this session.
    if not role and not jd_snap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请填写目标岗位或粘贴本场 JD 后再开始模拟面试",
        )
    if not role:
        role = "目标岗位"

    # Only seed question 1; remaining questions are generated after each answer.
    try:
        drafts = build_questions(
            count=1,
            target_role=role,
            resume_snapshot=resume_snap,
            jd_snapshot=jd_snap or None,
            retriever=retriever,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("build_questions failed role=%s", role)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="暂无法生成面试题，请稍后重试或检查知识库",
        ) from None
    if not drafts:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="暂无法生成面试题，请稍后重试或检查知识库",
        )
    first = drafts[0]

    session = InterviewSession(
        user_id=user_id,
        status="in_progress",
        question_count=question_count,
        target_role=role,
        resume_id=resume_id,
        jd_id=None,
        resume_snapshot=resume_snap,
        jd_snapshot=jd_snap,
        report=None,
    )
    try:
        db.add(session)
        db.flush()
        db.add(
            InterviewTurn(
                session_id=session.id,
                seq=1,
                question=strip_internal_ids(first.question),
                reference_text=first.reference_text or "",
            )
        )
        db.commit()
    except ProgrammingError:
        db.rollback()
        logger.exception("interview create_session DB programming error (missing migration?)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="面试数据表未就绪，请联系管理员执行数据库迁移",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.exception("interview create_session DB error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="创建面试场次失败，请稍后重试",
        ) from None
    return get_session_for_user(db, session.id, user_id)


def submit_answer(
    db: Session,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    answer: str,
    credentials: ProviderCredentials | None,
    retriever: Any | None,
) -> dict[str, Any]:
    session = get_session_for_user(db, session_id, user_id)
    if session.status != "in_progress":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="本场面试已结束")
    text = (answer or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="回答不能为空")

    turns = sorted(session.turns or [], key=lambda t: t.seq)
    current = next((t for t in turns if not (t.answer or "").strip()), None)
    if current is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有待回答的题目")

    scored = score_turn(
        question=current.question,
        answer=text,
        reference=current.reference_text or "",
        target_role=session.target_role or "",
        credentials=credentials,
    )
    current.answer = text
    current.score = int(scored.score)
    current.feedback = strip_internal_ids(scored.feedback)
    current.dimensions = scored.dimensions_dict()
    db.add(current)

    answered_count = sum(
        1 for t in turns if (t.answer or "").strip() or t.id == current.id
    )
    total = int(session.question_count or 5)

    if answered_count < total:
        prior_payload = [
            {
                "seq": t.seq,
                "question": t.question,
                "answer": current.answer if t.id == current.id else (t.answer or ""),
                "score": current.score if t.id == current.id else t.score,
            }
            for t in turns
        ]
        # Ensure current is reflected
        for row in prior_payload:
            if row["seq"] == current.seq:
                row["answer"] = current.answer
                row["score"] = current.score
        try:
            draft = next_question(
                seq=answered_count + 1,
                total=total,
                target_role=session.target_role or "",
                resume_snapshot=session.resume_snapshot or {},
                jd_snapshot=session.jd_snapshot or {},
                prior_turns=prior_payload,
                credentials=credentials,
                retriever=retriever,
            )
        except Exception:
            logger.exception("next_question failed; using safe opening fallback")
            draft = build_questions(
                count=1,
                target_role=session.target_role or "",
                resume_snapshot=session.resume_snapshot or {},
                jd_snapshot=session.jd_snapshot or None,
                retriever=None,
            )[0]
        db.add(
            InterviewTurn(
                session_id=session.id,
                seq=answered_count + 1,
                question=strip_internal_ids(draft.question),
                reference_text=draft.reference_text or "",
            )
        )
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("interview persist next question failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="保存下一题失败，请稍后重试",
            ) from None
        session = get_session_for_user(db, session_id, user_id)
        return {
            "done": False,
            "scored_turn": _turn_public(current),
            "session": session_public(session),
        }

    # Finalize report
    answered_payload = [
        {
            "seq": t.seq,
            "question": t.question,
            "score": t.score,
            "feedback": t.feedback,
            "dimensions": t.dimensions or {},
        }
        for t in turns
    ]
    # include just-updated current
    for row in answered_payload:
        if row["seq"] == current.seq:
            row["score"] = current.score
            row["feedback"] = current.feedback
            row["dimensions"] = current.dimensions or {}

    report = summarize_report(
        target_role=session.target_role or "",
        resume_snapshot=session.resume_snapshot or {},
        jd_snapshot=session.jd_snapshot or {},
        turns=answered_payload,
        credentials=credentials,
        retriever=retriever,
    )
    public = report.model_dump_public()
    public["disclaimer"] = DISCLAIMER
    # strip any residual ids in nested strings
    public["advice"] = strip_internal_ids(str(public.get("advice") or ""))
    for g in public.get("gaps") or []:
        if isinstance(g, dict):
            g["skill"] = strip_internal_ids(str(g.get("skill") or ""))
            g["suggestion"] = strip_internal_ids(str(g.get("suggestion") or ""))

    session.report = public
    session.status = "completed"
    db.add(session)
    db.commit()
    session = get_session_for_user(db, session_id, user_id)
    return {
        "done": True,
        "scored_turn": _turn_public(current),
        "session": session_public(session, include_report=True),
        "report": public,
    }


def get_report(db: Session, *, session_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    session = get_session_for_user(db, session_id, user_id)
    if session.status != "completed" or not session.report:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告尚未生成")
    return {
        "session_id": str(session.id),
        "target_role": session.target_role or "",
        "report": session.report,
    }
