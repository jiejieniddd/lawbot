from __future__ import annotations

import json
import logging
import re
from typing import Any

from lawbot.agent.citations import strip_internal_ids
from lawbot.agent.interview.prompts import (
    NEXT_QUESTION_SYSTEM,
    REPORT_SYSTEM,
    SCORE_SYSTEM,
    next_question_user_prompt,
    report_user_prompt,
    score_user_prompt,
)
from lawbot.agent.interview.schemas import (
    DraftQuestion,
    GapItem,
    InterviewReport,
    TurnBrief,
    TurnScore,
)
from lawbot.agent.tools import ToolContext, load_role_skill_map
from lawbot.domain.resume_schema import ResumeProfile
from lawbot.llm.client import ProviderCredentials, complete_text

logger = logging.getLogger(__name__)

# Opening / no-resume: never assume a prior project or resume.
_FALLBACK_OPENING = [
    ("请做一分钟自我介绍，并说明为何适合「{role}」岗位。", "结构：背景→技能→匹配动机"),
    ("你为什么想做「{role}」？最近在为这个方向做了哪些准备？", "动机真实 + 可验证准备"),
]

_FALLBACK_NO_RESUME = [
    ("针对「{role}」，请解释一个你认为最核心的技术概念及其适用场景。", "概念正确 + 落地场景"),
    ("如果线上服务变慢，你会如何排查？", "监控→瓶颈→验证→回滚"),
    ("你如何学习一门新技术，并验证自己真的学会了？", "学习路径 + 小步验证"),
    ("描述一次协作或需求变更中的处理方式（课程/社团/实习皆可）。", "沟通与优先级"),
    ("对该岗位，你还有哪些短板，准备如何补齐？", "诚实 + 可执行计划"),
    ("你有什么问题想问面试官？", "角色认知 / 团队节奏"),
    (
        "若有项目、实习或课设经历可以举一例说明你的贡献；"
        "若没有，请讲一次课程练习或自学任务中你如何解决问题。",
        "中性举例；勿假设必有商业项目",
    ),
]

_FALLBACK_WITH_RESUME = [
    ("请结合简历，讲一个最能体现你能力的项目：目标、技术选型与你的贡献。", "STAR；可量化结果"),
    ("挑一个简历中的核心技能，说明原理与你用过的场景。", "概念 + 简历证据"),
    ("如果线上服务变慢，你会如何排查？", "监控→瓶颈→验证→回滚"),
    ("描述一次协作冲突或需求变更，你如何处理？", "沟通与优先级"),
    ("对该岗位，对照简历你还有哪些短板，准备如何补齐？", "诚实 + 可执行计划"),
    ("你有什么问题想问面试官？", "角色认知 / 团队节奏"),
]

_PROJECT_ASSUME_RE = re.compile(
    r"(这个项目|该项目|你的项目|你负责的项目|简历里|简历中|结合你做过的|在你参与的项目)",
    re.IGNORECASE,
)
_PROJECT_CLUE_RE = re.compile(
    r"(项目|实习|课设|毕业设计|负责过|做过|参与过|开发了|上线过)",
)


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    blob = match.group(0) if match else raw
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _resume_profile(snapshot: dict[str, Any] | None) -> ResumeProfile:
    if not isinstance(snapshot, dict):
        return ResumeProfile()
    structured = snapshot.get("structured") if isinstance(snapshot.get("structured"), dict) else {}
    payload = dict(structured) if structured else dict(snapshot)
    if snapshot.get("skills") and not payload.get("skills"):
        payload["skills"] = snapshot.get("skills")
    if snapshot.get("intent") and not payload.get("intent"):
        payload["intent"] = snapshot.get("intent")
    try:
        return ResumeProfile.from_dict(payload)
    except Exception:
        return ResumeProfile(
            skills=[str(s) for s in (payload.get("skills") or []) if s],
            intent=str(payload.get("intent") or ""),
            summary=str(payload.get("summary") or ""),
        )


def _market_skills(target_role: str) -> list[str]:
    role = (target_role or "").strip()
    if not role:
        return []
    mapping = load_role_skill_map()
    role_l = role.lower()
    for key, skills in mapping.items():
        if key.lower() in role_l or role_l in key.lower():
            return [str(s) for s in skills if s][:16]
    # fuzzy: any key token overlap
    for key, skills in mapping.items():
        if any(tok and tok in role_l for tok in re.split(r"[\s/|]+", key.lower()) if len(tok) > 1):
            return [str(s) for s in skills if s][:16]
    return []


def _jd_skills(jd_snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(jd_snapshot, dict):
        return []
    raw = jd_snapshot.get("skills") or (jd_snapshot.get("structured") or {}).get("skills")
    if isinstance(raw, list):
        return [str(s) for s in raw if s][:12]
    return []


def _neutralize_project_question(q: str, *, has_resume: bool) -> str | None:
    """Drop or rewrite questions that assume a known project when inappropriate."""
    text = (q or "").strip()
    if not text:
        return None
    if has_resume:
        return text
    if _PROJECT_ASSUME_RE.search(text):
        # Skip hard project-presupposition items from KB for no-resume opening pool.
        return None
    return text


def _skill_probe_questions(role: str, skills: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for skill in skills[:4]:
        out.append(
            (
                f"针对「{role}」常见要求，请简述 {skill} 是什么、适用场景与你了解的注意事项。",
                f"{skill} 概念与场景",
            )
        )
    if not out:
        out.append(
            (
                f"请从「{role}」岗位出发，举一个你会重点准备的技术点并讲清原理。",
                "岗位基础技术",
            )
        )
    return out


def _append_draft(
    drafts: list[DraftQuestion],
    seen: set[str],
    question: str,
    reference: str,
    *,
    limit: int,
) -> bool:
    q = strip_internal_ids((question or "").strip())[:240]
    if not q:
        return len(drafts) >= limit
    key = q[:60]
    if key in seen:
        return len(drafts) >= limit
    seen.add(key)
    drafts.append(DraftQuestion(question=q, reference_text=strip_internal_ids(reference or "")[:800]))
    return len(drafts) >= limit


def build_questions(
    *,
    count: int,
    target_role: str,
    resume_snapshot: dict[str, Any],
    jd_snapshot: dict[str, Any] | None,
    retriever: Any | None,
) -> list[DraftQuestion]:
    """Build up to `count` questions. Prefer calling with count=1 at session start."""
    count = max(1, min(int(count or 1), 8))
    has_resume = _has_usable_resume(resume_snapshot)
    profile = _resume_profile(resume_snapshot) if has_resume else ResumeProfile()
    skills = list(profile.skills[:8]) if has_resume else []
    role = (target_role or profile.intent or "").strip() or "软件开发"
    jd_skills = _jd_skills(jd_snapshot)
    market = _market_skills(role)
    focus_skills = []
    for s in jd_skills + market + skills:
        if s and s not in focus_skills:
            focus_skills.append(s)

    drafts: list[DraftQuestion] = []
    seen: set[str] = set()

    # 1) Opening always first for cold start / no project context
    for q, ref in _FALLBACK_OPENING:
        if _append_draft(drafts, seen, q.format(role=role), ref, limit=count):
            return drafts[:count]

    # 2) Resume path: allow project dig; no-resume: skill probes + safe bank
    bank = _FALLBACK_WITH_RESUME if has_resume else (_skill_probe_questions(role, focus_skills) + _FALLBACK_NO_RESUME)
    for q, ref in bank:
        personalized = q.format(role=role) if "{role}" in q else q
        if not has_resume:
            personalized = _neutralize_project_question(personalized, has_resume=False) or ""
            if not personalized:
                continue
        if _append_draft(drafts, seen, personalized, ref, limit=count):
            return drafts[:count]

    # 3) KB fill (filtered when no resume)
    jd_text = ""
    if isinstance(jd_snapshot, dict):
        jd_text = str(jd_snapshot.get("raw_text") or jd_snapshot.get("text") or "")[:500]
    query = f"{role} 面试 {' '.join(focus_skills[:6])} {jd_text[:80]}".strip()
    if retriever is not None and len(drafts) < count:
        try:
            chunks = retriever.retrieve(query, top_k=max(count * 3, 8), domains=["interview_qa"])
        except TypeError:
            try:
                chunks = retriever.retrieve(query, top_k=max(count * 3, 8))
            except Exception:
                logger.exception("interview retrieve failed")
                chunks = []
        except Exception:
            logger.exception("interview retrieve failed")
            chunks = []
        for chunk in chunks or []:
            cite = getattr(chunk, "citation", None)
            title = str(getattr(cite, "law_name", None) or getattr(cite, "title", None) or "").strip()
            text = str(getattr(cite, "text", None) or "").strip()
            if not text and not title:
                continue
            raw_q = title if title.endswith("？") or title.endswith("?") else (
                f"请结合岗位「{role}」回答：{title}" if title else text.split("\n", 1)[0][:120]
            )
            q = _neutralize_project_question(raw_q, has_resume=has_resume)
            if not q:
                continue
            ref = strip_internal_ids(f"{title}\n{text}".strip())[:800]
            if _append_draft(drafts, seen, q, ref, limit=count):
                break

    # Ensure at least one question
    if not drafts:
        q, ref = _FALLBACK_OPENING[0]
        drafts.append(
            DraftQuestion(question=strip_internal_ids(q.format(role=role)), reference_text=ref)
        )
    return drafts[:count]


def extract_answer_clues(answers: list[str]) -> dict[str, Any]:
    """Detect project/internship mentions and rough skill tokens from prior answers."""
    blob = "\n".join(a for a in answers if a).strip()
    project_hints: list[str] = []
    if blob and _PROJECT_CLUE_RE.search(blob):
        # Capture short noun phrases around clue words
        for m in re.finditer(
            r"([\u4e00-\u9fffA-Za-z0-9_\-]{2,24}?(?:项目|实习|课设|毕业设计))",
            blob,
        ):
            hint = m.group(1).strip()
            if hint and hint not in project_hints:
                project_hints.append(hint)
        if not project_hints:
            project_hints.append("考生提及的项目/实习经历")
    skill_hints: list[str] = []
    for token in (
        "Python",
        "Java",
        "Go",
        "FastAPI",
        "Django",
        "Spring",
        "Redis",
        "MySQL",
        "PostgreSQL",
        "Kafka",
        "Docker",
        "Kubernetes",
        "K8s",
        "Linux",
        "React",
        "Vue",
        "PyTorch",
        "TensorFlow",
    ):
        if re.search(rf"\b{re.escape(token)}\b", blob, re.I) or token.lower() in blob.lower():
            if token not in skill_hints:
                skill_hints.append(token)
    return {
        "has_project_clue": bool(project_hints),
        "project_hints": project_hints[:6],
        "skill_hints": skill_hints[:10],
    }


def _fallback_next_question(
    *,
    seq: int,
    total: int,
    role: str,
    has_resume: bool,
    clues: dict[str, Any],
    asked: set[str],
) -> DraftQuestion:
    # Late questions: wrap-up / reverse QA
    if seq >= total:
        q, ref = ("你有什么问题想问面试官？", "角色认知 / 团队节奏")
        return DraftQuestion(question=q, reference_text=ref)
    if seq >= max(total - 1, 2) and total >= 5:
        q = f"对该岗位「{role}」，你还有哪些短板，准备如何补齐？"
        if q[:60] not in asked:
            return DraftQuestion(question=q, reference_text="诚实 + 可执行计划")

    if clues.get("has_project_clue") and clues.get("project_hints"):
        hint = str(clues["project_hints"][0])
        q = (
            f"你提到了「{hint}」，请具体说明你在其中的职责、用到的技术，以及遇到的一个难点与解决方式。"
        )
        return DraftQuestion(question=strip_internal_ids(q), reference_text="基于考生线索追问 STAR")

    if has_resume:
        for q, ref in _FALLBACK_WITH_RESUME:
            personalized = q.format(role=role) if "{role}" in q else q
            if personalized[:60] not in asked:
                return DraftQuestion(question=personalized, reference_text=ref)

    for q, ref in _skill_probe_questions(role, list(clues.get("skill_hints") or [])) + _FALLBACK_NO_RESUME:
        personalized = q.format(role=role) if "{role}" in q else q
        personalized = _neutralize_project_question(personalized, has_resume=False) or personalized
        if personalized[:60] not in asked:
            return DraftQuestion(question=strip_internal_ids(personalized), reference_text=ref)

    q, ref = _FALLBACK_OPENING[0]
    return DraftQuestion(question=q.format(role=role), reference_text=ref)


def next_question(
    *,
    seq: int,
    total: int,
    target_role: str,
    resume_snapshot: dict[str, Any],
    jd_snapshot: dict[str, Any] | None,
    prior_turns: list[dict[str, Any]],
    credentials: ProviderCredentials | None,
    retriever: Any | None = None,
) -> DraftQuestion:
    """Generate the next interview question from prior Q&A context."""
    _ = retriever
    has_resume = _has_usable_resume(resume_snapshot)
    profile = _resume_profile(resume_snapshot) if has_resume else ResumeProfile()
    role = (target_role or profile.intent or "").strip() or "软件开发"
    answers = [str(t.get("answer") or "") for t in prior_turns]
    clues = extract_answer_clues(answers)
    if has_resume and profile.projects:
        for p in profile.projects[:3]:
            name = getattr(p, "name", None) or (p.get("name") if isinstance(p, dict) else "")
            if name and name not in clues["project_hints"]:
                clues["project_hints"].append(str(name))
                clues["has_project_clue"] = True
    asked = {str(t.get("question") or "")[:60] for t in prior_turns}

    prior_qa = "\n".join(
        f"Q{t.get('seq')}: {t.get('question')}\nA: {str(t.get('answer') or '')[:300]}"
        for t in prior_turns[-4:]
    )
    jd_summary = ""
    if isinstance(jd_snapshot, dict):
        jd_summary = str(jd_snapshot.get("raw_text") or jd_snapshot.get("text") or "")[:400]

    if credentials is not None:
        try:
            raw = complete_text(
                prompt=next_question_user_prompt(
                    target_role=role,
                    seq=seq,
                    total=total,
                    has_resume=has_resume,
                    project_hints=list(clues.get("project_hints") or []),
                    skill_hints=list(clues.get("skill_hints") or []) + list(profile.skills[:6]),
                    prior_qa=prior_qa,
                    jd_summary=jd_summary,
                ),
                credentials=credentials,
                system=NEXT_QUESTION_SYSTEM,
            ) or ""
            data = _parse_json_object(raw)
            q = strip_internal_ids(str(data.get("question") or "").strip())
            if q and not (not has_resume and not clues.get("has_project_clue") and _PROJECT_ASSUME_RE.search(q)):
                if q[:60] not in asked:
                    return DraftQuestion(
                        question=q[:240],
                        reference_text=strip_internal_ids(str(data.get("reference_text") or ""))[:800],
                    )
        except Exception:
            logger.exception("next_question LLM failed; using fallback")

    return _fallback_next_question(
        seq=seq,
        total=total,
        role=role,
        has_resume=has_resume,
        clues=clues,
        asked=asked,
    )


def score_turn(
    *,
    question: str,
    answer: str,
    reference: str,
    target_role: str,
    credentials: ProviderCredentials | None,
) -> TurnScore:
    answer = (answer or "").strip()
    if not answer:
        return TurnScore(score=20, feedback="未作答或过短，建议按要点完整表述。", clarity=20, depth=15, relevance=25)

    if credentials is None:
        length = len(answer)
        base = 45 if length < 40 else 62 if length < 160 else 72
        return TurnScore(
            score=base,
            feedback="（模拟评分）回答已记录；启用 LLM 后可获得更细的能力点评。",
            clarity=base,
            depth=max(30, base - 8),
            relevance=min(90, base + 5),
        )

    prompt = score_user_prompt(
        question=question,
        answer=answer,
        reference=reference,
        target_role=target_role,
    )
    try:
        raw = complete_text(prompt=prompt, credentials=credentials, system=SCORE_SYSTEM) or ""
        data = _parse_json_object(raw)
        scored = TurnScore.model_validate(
            {
                "score": int(data.get("score", 60)),
                "feedback": strip_internal_ids(str(data.get("feedback") or "")),
                "clarity": int(data.get("clarity", data.get("score", 60))),
                "depth": int(data.get("depth", data.get("score", 60))),
                "relevance": int(data.get("relevance", data.get("score", 60))),
            }
        )
        scored.feedback = strip_internal_ids(scored.feedback) or "已记录作答。"
        return scored
    except Exception:
        logger.exception("interview score_turn LLM failed")
        return TurnScore(
            score=58,
            feedback="评分服务暂不可用，已给出保守分；请对照参考要点自行复盘。",
            clarity=58,
            depth=55,
            relevance=60,
        )


def _has_usable_resume(resume_snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(resume_snapshot, dict) or not resume_snapshot:
        return False
    if resume_snapshot.get("parse_status") and resume_snapshot.get("parse_status") != "ready":
        return False
    profile = _resume_profile(resume_snapshot)
    return bool(profile.skills or profile.projects or profile.summary or profile.intent or resume_snapshot.get("id"))


def summarize_report(
    *,
    target_role: str,
    resume_snapshot: dict[str, Any],
    jd_snapshot: dict[str, Any] | None,
    turns: list[dict[str, Any]],
    credentials: ProviderCredentials | None,
    retriever: Any | None = None,
) -> InterviewReport:
    has_resume = _has_usable_resume(resume_snapshot)
    profile = _resume_profile(resume_snapshot) if has_resume else ResumeProfile()
    role = (target_role or profile.intent or "").strip() or "目标岗位"
    briefs: list[TurnBrief] = []
    dim_sums = {"clarity": 0, "depth": 0, "relevance": 0}
    dim_n = 0
    scores: list[int] = []
    for t in turns:
        sc = int(t.get("score") or 0)
        scores.append(sc)
        dims = t.get("dimensions") if isinstance(t.get("dimensions"), dict) else {}
        for k in dim_sums:
            if k in dims:
                dim_sums[k] += int(dims[k])
        if dims:
            dim_n += 1
        briefs.append(
            TurnBrief(
                seq=int(t.get("seq") or 0),
                question=strip_internal_ids(str(t.get("question") or "")),
                score=sc,
                feedback=strip_internal_ids(str(t.get("feedback") or "")),
            )
        )
    total = int(round(sum(scores) / len(scores))) if scores else 0
    averages = {
        k: int(round(v / dim_n)) if dim_n else total for k, v in dim_sums.items()
    }

    market = _market_skills(role)
    skill_l = {s.lower() for s in profile.skills} if has_resume else set()
    jd_skills: list[str] = []
    if isinstance(jd_snapshot, dict):
        raw_skills = jd_snapshot.get("skills") or (jd_snapshot.get("structured") or {}).get("skills")
        if isinstance(raw_skills, list):
            jd_skills = [str(s) for s in raw_skills if s]
    suggested = []
    for s in jd_skills + market:
        if s.lower() not in skill_l and s not in suggested:
            suggested.append(s)

    # Optional KB titles as gap hints (no source_id)
    if retriever is not None and len(suggested) < 5:
        try:
            ctx = ToolContext(
                retriever=retriever,
                active_resume=resume_snapshot if has_resume else None,
                active_jd=jd_snapshot or {},
            )
            from lawbot.agent.tools import SearchKbArgs, _search_kb

            hits = _search_kb(
                SearchKbArgs(query=f"{role} 技能", top_k=4, domains=["job_skills"]),
                ctx,
            )
            for hit in hits:
                title = str(hit.get("law_name") or "").strip()
                if title and title not in suggested:
                    suggested.append(title)
        except Exception:
            logger.exception("interview gap kb search failed")

    suggested = suggested[:8]
    turn_lines = "\n".join(
        f"- 第{b.seq}题（{b.score}分）：{b.feedback or b.question[:40]}" for b in briefs
    )
    if has_resume:
        skill_hint = "、".join(profile.skills[:6]) or "简历技能"
        advice = (
            f"结合你的简历（{skill_hint}）与岗位「{role}」，"
            f"优先补齐：{'、'.join(suggested[:5]) or '对照 JD 细化技能树'}；"
            "用项目细节证明已有技能，缺口用小项目或刷题补证据。"
        )
        gaps = [
            GapItem(
                skill=s,
                suggestion=f"相对简历与岗位「{role}」：补齐 {s} 的项目或刷题证据",
            )
            for s in suggested
        ]
        resume_note = "已结合当前简历技能/项目做相对岗位初评。"
        resume_summary = profile.prompt_block()[:800]
    else:
        advice = (
            f"未提供简历，以下为岗位「{role}」通用初评。"
            f"建议优先掌握：{'、'.join(suggested[:5]) or '该方向常见技能'}；"
            "上传简历后复测，缺口会更贴合你的项目经历。"
        )
        gaps = [
            GapItem(
                skill=s,
                suggestion=f"岗位「{role}」通用要求：建议补齐 {s}（上传简历后可对照个人项目复测）",
            )
            for s in suggested
        ]
        resume_note = "未提供简历，为岗位通用初评；上传简历后复测更准。"
        resume_summary = "（未提供简历）"

    if credentials is not None:
        try:
            raw = complete_text(
                prompt=report_user_prompt(
                    target_role=role,
                    resume_summary=resume_summary,
                    jd_summary=str((jd_snapshot or {}).get("raw_text") or (jd_snapshot or {}).get("text") or "")[:600],
                    turn_summaries=turn_lines,
                    suggested_gaps=suggested,
                ),
                credentials=credentials,
                system=REPORT_SYSTEM,
            ) or ""
            data = _parse_json_object(raw)
            if data.get("advice"):
                advice = strip_internal_ids(str(data["advice"]))
                if not has_resume and "未提供简历" not in advice:
                    advice = f"未提供简历，为岗位通用初评。{advice}"
            raw_gaps = data.get("gap_suggestions") or data.get("gaps") or []
            if isinstance(raw_gaps, list) and raw_gaps:
                parsed: list[GapItem] = []
                for item in raw_gaps[:8]:
                    if isinstance(item, dict):
                        parsed.append(
                            GapItem(
                                skill=strip_internal_ids(str(item.get("skill") or item.get("name") or "技能")),
                                suggestion=strip_internal_ids(str(item.get("suggestion") or "")),
                            )
                        )
                    else:
                        text = strip_internal_ids(str(item))
                        if "：" in text:
                            skill, sug = text.split("：", 1)
                        elif ":" in text:
                            skill, sug = text.split(":", 1)
                        else:
                            skill, sug = text, f"针对「{role}」补齐"
                        parsed.append(GapItem(skill=skill.strip() or "技能", suggestion=sug.strip()))
                if parsed:
                    gaps = parsed
        except Exception:
            logger.exception("interview summarize_report LLM failed")

    # Ensure role name appears in gap copy so different targets are distinguishable
    for g in gaps:
        if role and role not in g.suggestion:
            prefix = "相对简历与岗位" if has_resume else "相对岗位"
            g.suggestion = strip_internal_ids(
                f"{prefix}「{role}」：{g.suggestion or '建议补项目证据'}"
            )

    return InterviewReport(
        total_score=total,
        dimension_averages=averages,
        turns=briefs,
        gaps=gaps,
        advice=strip_internal_ids(advice),
        target_role=role,
        has_resume=has_resume,
        resume_note=resume_note,
    )
