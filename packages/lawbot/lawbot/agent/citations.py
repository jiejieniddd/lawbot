"""Check generated article citations against this turn's search hits."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Narrow to statute-style titles so career KB titles are not stripped as false cites.
ARTICLE_RE = re.compile(
    r"《([^》]{1,80}(?:法|条例|规定|办法|细则))》(第[0-9零一二三四五六七八九十百千]{1,16}条)"
)
OMITTED_NOTE = "部分引用未通过核验，已省略"
DOUBT_MARK = "引用存疑"

Regenerate = Callable[[str, list[tuple[str, str]], list[dict[str, Any]]], str]


@dataclass
class CitationRepair:
    text: str
    citations: list[dict[str, Any]]
    doubtful: list[tuple[str, str]] = field(default_factory=list)


def status_label(status: str | None) -> str:
    raw = (status or "").strip()
    if raw in {"有效", "现行有效"}:
        return "现行有效"
    if raw in {"已修订", "修订"}:
        return "已修订"
    if raw in {"已废止", "废止"}:
        return "已废止"
    return "效力未标注"


def normalize_law_name(name: str) -> str:
    return (name or "").replace("《", "").replace("》", "").strip()


def normalize_article(article: str) -> str:
    text = (article or "").strip()
    if text.startswith("第"):
        text = text[1:]
    if text.endswith("条"):
        text = text[:-1]
    return text.strip()


def display_ref(law_name: str, article_no: str) -> str:
    law = normalize_law_name(law_name)
    article = (article_no or "").strip()
    # CareerBot knowledge categories are not statute article numbers.
    if article in {"interview_qa", "tech_docs", "gotchas", "self_test", "job_skills"} or (
        article and not article.startswith("第") and "条" not in article
    ):
        label = f" / {article}" if article else ""
        return f"【{law}{label}】"
    if re.fullmatch(r"第.+条", article):
        return f"《{law}》{article}"
    return f"《{law}》第{article}条"


def format_basis_line(hit: dict[str, Any]) -> str:
    ref = display_ref(str(hit.get("law_name") or ""), str(hit.get("article_no") or ""))
    bits = [f"{ref}（效力：{status_label(hit.get('status'))}）"]
    if hit.get("effective_date"):
        bits.append(str(hit["effective_date"]))
    snippet = str(hit.get("text") or "").strip()
    if snippet:
        bits.append(snippet[:80])
    return "｜".join(bits)


# Internal KB id shapes that must never appear in student-facing answer text.
_SOURCE_ID_EQ_RE = re.compile(r"source_id\s*=\s*\S+", re.IGNORECASE)
_PREFIXED_ID_RE = re.compile(
    r"\b(?:ai_job|interview_zh|dev_docs|cmmlu(?:_cs)?|hive(?:_corpus)?)"
    r":[A-Za-z0-9_.:/-]{6,}\b",
    re.IGNORECASE,
)
_PAREN_INTERNAL_ID_RE = re.compile(
    r"[（(]\s*(?:source_id\s*=\s*)?(?:ai_job|interview_zh|dev_docs|cmmlu(?:_cs)?|hive(?:_corpus)?)"
    r":[A-Za-z0-9_.:/-]{6,}\s*[）)]",
    re.IGNORECASE,
)
_BARE_HASH_FOOTNOTE_RE = re.compile(
    r"[（(]\s*[a-f0-9]{12,}\s*[）)]",
    re.IGNORECASE,
)


def strip_internal_ids(text: str) -> str:
    """Remove residual internal KB ids from model output without harming normal tech terms."""
    if not text:
        return text
    cleaned = _PAREN_INTERNAL_ID_RE.sub("", text)
    cleaned = _SOURCE_ID_EQ_RE.sub("", cleaned)
    cleaned = _PREFIXED_ID_RE.sub("", cleaned)
    cleaned = _BARE_HASH_FOOTNOTE_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _article_key(law_name: str, article_no: str) -> tuple[str, str]:
    return (normalize_law_name(law_name), normalize_article(article_no))


def _hit_key(hit: dict[str, Any]) -> tuple[str, str] | None:
    law_name = str(hit.get("law_name") or "").strip()
    article_no = str(hit.get("article_no") or "").strip()
    if not law_name or not article_no or not str(hit.get("text") or "").strip():
        return None
    return _article_key(law_name, article_no)


def supported_index(hits: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for hit in hits:
        key = _hit_key(hit)
        if key is not None:
            indexed[key] = hit
    return indexed


def extract_article_refs(text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in ARTICLE_RE.finditer(text or "")]


def _collect_refs(text: str, citations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    found = list(extract_article_refs(text))
    for item in citations:
        law_name = str(item.get("law_name") or "").strip()
        article_no = str(item.get("article_no") or "").strip()
        if law_name and article_no:
            found.append((law_name, article_no))
    return found


def unsupported_refs(
    text: str,
    citations: list[dict[str, Any]],
    hits: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    indexed = supported_index(hits)
    bad: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for law_name, article_no in _collect_refs(text, citations):
        key = _article_key(law_name, article_no)
        if key in seen:
            continue
        seen.add(key)
        if key not in indexed:
            bad.append((law_name, article_no))
    return bad


def _ref_pattern(law_name: str, article_no: str) -> re.Pattern[str]:
    number = re.escape(normalize_article(article_no))
    law = re.escape(normalize_law_name(law_name))
    return re.compile(rf"《{law}》第?{number}条(?:（引用存疑）)?")


def mark_doubtful(text: str, refs: list[tuple[str, str]]) -> str:
    marked = text
    for law_name, article_no in refs:
        pattern = _ref_pattern(law_name, article_no)

        def _repl(match: re.Match[str]) -> str:
            raw = match.group(0)
            if raw.endswith("（引用存疑）"):
                return raw
            return f"{raw}（引用存疑）"

        marked = pattern.sub(_repl, marked)
    return marked


def _strip_refs(text: str, refs: list[tuple[str, str]]) -> str:
    cleaned = text
    for law_name, article_no in refs:
        cleaned = _ref_pattern(law_name, article_no).sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _with_omitted_note(text: str) -> str:
    if OMITTED_NOTE in text:
        return text
    heading = "## 法律依据"
    if heading in text:
        return text.replace(heading, f"{heading}\n\n{OMITTED_NOTE}", 1)
    return f"{OMITTED_NOTE}\n\n{text}"


def _keep_citations(
    citations: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    dropped: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    indexed = supported_index(hits)
    kept: list[dict[str, Any]] = []
    for item in citations:
        key = _article_key(str(item.get("law_name") or ""), str(item.get("article_no") or ""))
        if key in indexed and key not in dropped:
            kept.append(item)
    return kept


def repair_citations(
    text: str,
    citations: list[dict[str, Any]],
    hits: list[dict[str, Any]],
    regenerate: Regenerate,
) -> CitationRepair:
    """Mark unsupported cites, regenerate once, then drop whatever still fails."""
    doubtful = unsupported_refs(text, citations, hits)
    if not doubtful:
        return CitationRepair(text=text, citations=list(citations), doubtful=[])
    marked = mark_doubtful(text, doubtful)
    try:
        second = regenerate(marked, doubtful, hits)
    except Exception:
        second = ""
    if not str(second or "").strip():
        second = marked
    still_bad = unsupported_refs(second, citations, hits)
    if not still_bad:
        return CitationRepair(
            text=second,
            citations=_keep_citations(citations, hits, set()),
            doubtful=doubtful,
        )
    cleaned = _with_omitted_note(_strip_refs(second, still_bad))
    dropped = {_article_key(law_name, article_no) for law_name, article_no in still_bad}
    return CitationRepair(
        text=cleaned,
        citations=_keep_citations(citations, hits, dropped),
        doubtful=doubtful,
    )


def needs_unverified_fallback(query: str, hits: list[dict[str, Any]]) -> bool:
    """Named article or an explicit repeal question with no matching hit."""
    named = extract_article_refs(query or "")
    indexed = supported_index(hits)
    if named and any(_article_key(law_name, article_no) not in indexed for law_name, article_no in named):
        return True
    if "废止" in (query or ""):
        if named:
            return False
        return not any(status_label(hit.get("status")) == "已废止" and _hit_key(hit) for hit in hits)
    return False
