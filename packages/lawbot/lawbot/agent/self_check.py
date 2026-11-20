"""Rule-first self-check before a legal report is streamed."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from lawbot.agent.citations import (
    OMITTED_NOTE,
    _article_key,
    _strip_refs,
    _with_omitted_note,
    extract_article_refs,
)
from lawbot.agent.tools import EmitLegalReportArgs, format_legal_report
from lawbot.llm.client import ProviderCredentials, complete_text

logger = logging.getLogger(__name__)

Action = Literal["pass", "rewrite", "downgrade"]

ABSOLUTE_PHRASES = (
    "肯定赢",
    "100%胜诉",
    "百分之百胜诉",
    "一定无罪",
    "保证要回全部款项",
    "保证全部要回",
    "稳赢",
    "必胜",
    "必然胜诉",
    "一定胜诉",
)
ABSOLUTE_REPLACEMENT = "结果存在不确定性，需结合事实与证据判断"

ASSERTION_MARKERS = (
    "解除劳动合同",
    "可以主张赔偿",
    "构成违约",
    "依法有权",
    "应当支付",
    "有权解除",
    "可以解除",
    "构成侵权",
    "应当赔偿",
    "可以请求",
    "有权要求",
)
UNSUPPORTED_REPLACEMENT = "检索结果未覆盖该点。"
SECTION_RE = re.compile(
    r"^## (法律依据|分析|建议|风险提示|免责声明)\s*$",
    re.MULTILINE,
)


@dataclass
class SelfCheckResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    action: Action = "pass"
    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)


def _split_sections(text: str) -> dict[str, str]:
    parts = SECTION_RE.split(text or "")
    sections: dict[str, str] = {}
    if len(parts) < 3:
        return sections
    # parts: [preamble, title1, body1, title2, body2, ...]
    for i in range(1, len(parts), 2):
        title = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections[title] = body.strip()
    return sections


def _join_sections(sections: dict[str, str], original: str) -> str:
    order = ["法律依据", "分析", "建议", "风险提示", "免责声明"]
    if not any(title in sections for title in order):
        return original
    blocks: list[str] = []
    for title in order:
        if title not in sections:
            continue
        body = sections[title].strip()
        blocks.append(f"## {title}\n\n{body}" if body else f"## {title}")
    return "\n\n".join(blocks).strip()


def _hit_corpus(hits: list[dict[str, Any]]) -> str:
    bits: list[str] = []
    for hit in hits:
        bits.append(str(hit.get("law_name") or ""))
        bits.append(str(hit.get("article_no") or ""))
        bits.append(str(hit.get("text") or ""))
    return "\n".join(bits)


def _sentence_supported(sentence: str, hits: list[dict[str, Any]]) -> bool | None:
    """True/False when rules decide; None when a short LLM check is needed."""
    corpus = _hit_corpus(hits)
    if not corpus.strip():
        return False
    refs = extract_article_refs(sentence)
    if refs:
        keys = {_article_key(law, article) for law, article in refs}
        hit_keys = {
            _article_key(str(hit.get("law_name") or ""), str(hit.get("article_no") or ""))
            for hit in hits
            if hit.get("law_name") and hit.get("article_no") and str(hit.get("text") or "").strip()
        }
        return bool(keys) and keys.issubset(hit_keys)
    markers = [marker for marker in ASSERTION_MARKERS if marker in sentence]
    if not markers:
        return True
    if any(marker in corpus for marker in markers):
        return True
    # Marker present but not in hits: still maybe related keywords in Chinese hits
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}", sentence)
    overlap = sum(1 for token in tokens if token in corpus and token not in ASSERTION_MARKERS)
    if overlap >= 2:
        return True
    if overlap == 0:
        return False
    return None


def _llm_sentence_supported(
    sentence: str,
    hits: list[dict[str, Any]],
    credentials: ProviderCredentials,
) -> bool:
    prompt = (
        "判断下面句子的法律结论是否能被检索片段支撑。"
        "只回答 yes 或 no。\n"
        f"句子：{sentence}\n"
        f"片段：{_hit_corpus(hits)[:1200]}\n"
    )
    try:
        raw = complete_text(
            prompt=prompt,
            credentials=credentials,
            system="你只回答 yes 或 no。",
        )
    except Exception:
        logger.exception("self-check LLM support probe failed")
        return False
    answer = (raw or "").strip().lower()
    return answer.startswith("yes") or answer.startswith("是")


def _rewrite_absolute(text: str) -> tuple[str, list[str]]:
    issues: list[str] = []
    rewritten = text
    for phrase in ABSOLUTE_PHRASES:
        if phrase in rewritten:
            issues.append(f"absolute:{phrase}")
            rewritten = rewritten.replace(phrase, ABSOLUTE_REPLACEMENT)
    return rewritten, issues


def _rewrite_unsupported_assertions(
    text: str,
    hits: list[dict[str, Any]],
    credentials: ProviderCredentials | None,
) -> tuple[str, list[str]]:
    sections = _split_sections(text)
    issues: list[str] = []
    llm_used = False
    for title in ("分析", "建议"):
        body = sections.get(title)
        if not body:
            continue
        sentences = re.split(r"(?<=[。！？；\n])", body)
        rewritten: list[str] = []
        for sentence in sentences:
            raw = sentence.strip()
            if not raw:
                rewritten.append(sentence)
                continue
            if not any(marker in raw for marker in ASSERTION_MARKERS) and not extract_article_refs(raw):
                rewritten.append(sentence)
                continue
            supported = _sentence_supported(raw, hits)
            if supported is None and credentials is not None and not llm_used:
                supported = _llm_sentence_supported(raw, hits, credentials)
                llm_used = True
            if supported is None:
                supported = False
            if supported:
                rewritten.append(sentence)
                continue
            issues.append(f"unsupported:{raw[:40]}")
            rewritten.append(UNSUPPORTED_REPLACEMENT)
        sections[title] = "".join(rewritten).strip()
    return _join_sections(sections, text), issues


def _citation_consistency(
    text: str,
    citations: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    body_refs = extract_article_refs(text)
    body_keys = {_article_key(law, article) for law, article in body_refs}
    cite_keys = {
        _article_key(str(item.get("law_name") or ""), str(item.get("article_no") or ""))
        for item in citations
        if item.get("law_name") and item.get("article_no")
    }

    missing_in_list = [ref for ref in body_refs if _article_key(*ref) not in cite_keys]
    missing_in_body = [
        item
        for item in citations
        if item.get("law_name")
        and item.get("article_no")
        and _article_key(str(item["law_name"]), str(item["article_no"])) not in body_keys
    ]

    cleaned = text
    kept = list(citations)
    if missing_in_list:
        issues.append("body_ref_not_in_citations")
        cleaned = _strip_refs(cleaned, missing_in_list)
        cleaned = _with_omitted_note(cleaned)
    if missing_in_body:
        issues.append("citation_not_in_body")
        drop = {
            _article_key(str(item.get("law_name") or ""), str(item.get("article_no") or ""))
            for item in missing_in_body
        }
        kept = [
            item
            for item in citations
            if _article_key(str(item.get("law_name") or ""), str(item.get("article_no") or ""))
            not in drop
        ]
        if OMITTED_NOTE not in cleaned:
            cleaned = _with_omitted_note(cleaned)
    return cleaned, kept, issues


def _downgrade_report(risk: str | None = None) -> str:
    return format_legal_report(
        EmitLegalReportArgs(
            legal_basis="检索结果未覆盖部分关键判断，以下仅作一般提示。",
            analysis="现有检索片段不足以支撑更具体的法律结论，请以核实后的事实与正式意见为准。",
            advice="建议先固定证据，并通过合法途径协商、投诉或咨询执业律师。",
            risk=(risk or "结果存在不确定性，重大决定前请寻求专业法律帮助。"),
        )
    )


def _still_has_absolute(text: str) -> bool:
    return any(phrase in text for phrase in ABSOLUTE_PHRASES)


def run_self_check(
    text: str,
    citations: list[dict[str, Any]],
    law_hits: list[dict[str, Any]],
    credentials: ProviderCredentials | None = None,
) -> SelfCheckResult:
    issues: list[str] = []
    current = text
    current_citations = list(citations)

    current, absolute_issues = _rewrite_absolute(current)
    issues.extend(absolute_issues)

    current, unsupported_issues = _rewrite_unsupported_assertions(
        current, law_hits, credentials
    )
    issues.extend(unsupported_issues)

    current, current_citations, consistency_issues = _citation_consistency(
        current, current_citations
    )
    issues.extend(consistency_issues)

    current, current_citations, more_consistency = _citation_consistency(
        current, current_citations
    )
    for item in more_consistency:
        if item not in issues:
            issues.append(item)

    if _still_has_absolute(current):
        sections = _split_sections(current)
        risk = sections.get("风险提示")
        return SelfCheckResult(
            passed=False,
            issues=issues,
            action="downgrade",
            text=_downgrade_report(risk=risk),
            citations=[],
        )

    # Any remaining assertion markers that still have no hit support → downgrade
    leftover = False
    for title in ("分析", "建议"):
        body = _split_sections(current).get(title) or ""
        for sentence in re.split(r"(?<=[。！？；\n])", body):
            raw = sentence.strip()
            if not raw or UNSUPPORTED_REPLACEMENT in raw:
                continue
            if any(marker in raw for marker in ASSERTION_MARKERS):
                supported = _sentence_supported(raw, law_hits)
                if supported is False:
                    leftover = True
                    break
        if leftover:
            break
    if leftover:
        sections = _split_sections(current)
        risk = sections.get("风险提示")
        return SelfCheckResult(
            passed=False,
            issues=issues + ["unsupported_remaining"],
            action="downgrade",
            text=_downgrade_report(risk=risk),
            citations=[],
        )

    if not issues:
        return SelfCheckResult(
            passed=True,
            issues=[],
            action="pass",
            text=current,
            citations=current_citations,
        )

    return SelfCheckResult(
        passed=False,
        issues=issues,
        action="rewrite",
        text=current,
        citations=current_citations,
    )
