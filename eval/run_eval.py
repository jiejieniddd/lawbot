#!/usr/bin/env python3
"""Run end-to-end gold cases against the current legal graph.

Usage (repo root):
  python eval/run_eval.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages" / "lawbot") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.agent.citations import extract_article_refs, supported_index  # noqa: E402
from lawbot.agent.graph import run_agent_stream  # noqa: E402
from lawbot.agent.self_check import ASSERTION_MARKERS, _sentence_supported  # noqa: E402
from lawbot.domain.schemas import ChatEvent  # noqa: E402
from lawbot.rag.fake import FakeRetriever  # noqa: E402

GOLD_PATH = ROOT / "eval" / "sample_gold.json"
REPORT_PATH = ROOT / "eval" / "last_report.json"


class EmptyRetriever:
    def retrieve(self, query: str, top_k: int = 3):
        return []


def _load_gold() -> list[dict[str, Any]]:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _pick_retriever(name: str):
    if name == "empty":
        return EmptyRetriever()
    return FakeRetriever()


def _final_state(events: list[Any]) -> dict[str, Any]:
    finals = [item for item in events if not isinstance(item, ChatEvent)]
    return dict(finals[-1]) if finals else {}


def _answer_text(events: list[Any], state: dict[str, Any]) -> str:
    tokens = [
        event.data.get("text", "")
        for event in events
        if isinstance(event, ChatEvent) and event.type == "token"
    ]
    joined = "".join(tokens)
    return joined or str(state.get("answer") or "")


def _citation_events(events: list[Any]) -> list[dict[str, Any]]:
    return [
        event.data
        for event in events
        if isinstance(event, ChatEvent) and event.type == "citation"
    ]


def _has_error(events: list[Any]) -> bool:
    return any(isinstance(event, ChatEvent) and event.type == "error" for event in events)


def _phrase_hit(text: str, phrase: str) -> bool:
    if any(ch in phrase for ch in ".+*?[]()|^$\\"):
        return re.search(phrase, text) is not None
    return phrase in text


def _observed_behavior(state: dict[str, Any], answer: str, events: list[Any]) -> str:
    phase = str(state.get("phase") or "")
    if _has_error(events) or phase == "out_of_scope":
        return "refuse"
    if phase == "followup" or "请补充：" in answer:
        return "clarify"
    if phase in {"no_basis", "staged"}:
        return "insufficient"
    if any(
        tip in answer
        for tip in ("未检索到明确依据", "检索结果未覆盖", "信息不足，建议补充")
    ):
        return "insufficient"
    if phase == "analyze":
        return "answer"
    return phase or "unknown"


def _refs_supported(answer: str, hits: list[dict[str, Any]]) -> bool:
    from lawbot.agent.citations import normalize_article, normalize_law_name

    indexed = supported_index(hits)
    for law, article in extract_article_refs(answer):
        key = (normalize_law_name(law), normalize_article(article))
        if key not in indexed:
            return False
    return True


def _has_unsupported_assertion(answer: str, hits: list[dict[str, Any]]) -> bool:
    for title in ("## 分析", "## 建议"):
        if title not in answer:
            continue
    # split roughly by sentence
    for sentence in re.split(r"(?<=[。！？；\n])", answer):
        raw = sentence.strip()
        if not raw:
            continue
        if not any(marker in raw for marker in ASSERTION_MARKERS):
            continue
        if "检索结果未覆盖" in raw:
            continue
        supported = _sentence_supported(raw, hits)
        if supported is False:
            return True
    return False


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    retriever = _pick_retriever(str(case.get("retriever") or "fake"))
    events = list(
        run_agent_stream(
            str(case["query"]),
            f"eval-{case['id']}",
            retriever=retriever,
            credentials=None,
            mock_sleep=0,
            history=list(case.get("history") or []),
        )
    )
    state = _final_state(events)
    answer = _answer_text(events, state)
    citations = _citation_events(events) or list(state.get("citations") or [])
    law_hits = list(state.get("law_hits") or citations)
    phase = str(state.get("phase") or "")
    tool_trace = list(state.get("tool_trace") or [])
    steps = len(tool_trace) + 1
    observed = _observed_behavior(state, answer, events)
    expected = str(case["expected_behavior"])
    issues: list[str] = []

    if observed != expected:
        issues.append(f"behavior:{observed}!={expected}")

    require_citations = bool(case.get("require_citations"))
    if require_citations and not citations:
        issues.append("missing_citations")
    if not require_citations and citations and expected in {"clarify", "refuse"}:
        issues.append("unexpected_citations")

    for phrase in case.get("forbidden_phrases") or []:
        if _phrase_hit(answer, str(phrase)):
            issues.append(f"forbidden:{phrase}")

    if expected == "clarify":
        if "请补充：" not in answer:
            issues.append("missing_followup_marker")
        if "## 简单说" in answer:
            issues.append("deterministic_template")

    if expected == "insufficient":
        tips = ("未检索到明确依据", "检索结果未覆盖", "信息不足，建议补充")
        if not any(tip in answer for tip in tips) and phase not in {"no_basis", "staged"}:
            issues.append("missing_insufficient_signal")

    verifiable = None
    if citations:
        verifiable = _refs_supported(answer, law_hits)

    unsupported = None
    if observed in {"answer", "insufficient"}:
        unsupported = _has_unsupported_assertion(answer, law_hits)

    return {
        "id": case["id"],
        "pass": not issues,
        "phase": phase,
        "observed_behavior": observed,
        "expected_behavior": expected,
        "steps": steps,
        "citation_count": len(citations),
        "citations_verifiable": verifiable,
        "unsupported_assertion": unsupported,
        "issues": issues,
        "answer_preview": answer[:180],
    }


def main() -> int:
    cases = _load_gold()
    results = [_evaluate_case(case) for case in cases]

    with_cites = [row for row in results if row["citation_count"] > 0]
    verifiable_ok = sum(1 for row in with_cites if row["citations_verifiable"] is True)
    citation_verifiable_rate = (verifiable_ok / len(with_cites)) if with_cites else 1.0

    assertion_rows = [
        row for row in results if row["unsupported_assertion"] is not None
    ]
    unsupported_n = sum(1 for row in assertion_rows if row["unsupported_assertion"])
    unsupported_assertion_rate = (
        unsupported_n / len(assertion_rows) if assertion_rows else 0.0
    )

    clarify_expected = [row for row in results if row["expected_behavior"] == "clarify"]
    clarify_hit = sum(
        1 for row in clarify_expected if row["observed_behavior"] == "clarify"
    )
    clarify_match_rate = (
        clarify_hit / len(clarify_expected) if clarify_expected else 1.0
    )

    avg_steps = sum(row["steps"] for row in results) / len(results) if results else 0.0
    passed = sum(1 for row in results if row["pass"])

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "citation_verifiable_rate": round(citation_verifiable_rate, 4),
        "unsupported_assertion_rate": round(unsupported_assertion_rate, 4),
        "clarify_match_rate": round(clarify_match_rate, 4),
        "average_steps": round(avg_steps, 4),
    }
    report = {"summary": summary, "cases": results}
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=== LawBot eval ===")
    print(f"cases: {summary['passed']}/{summary['total']} passed")
    print(f"citation_verifiable_rate: {summary['citation_verifiable_rate']:.2%}")
    print(f"unsupported_assertion_rate: {summary['unsupported_assertion_rate']:.2%}")
    print(f"clarify_match_rate: {summary['clarify_match_rate']:.2%}")
    print(f"average_steps: {summary['average_steps']:.2f}")
    print(f"report: {REPORT_PATH}")
    for row in results:
        mark = "PASS" if row["pass"] else "FAIL"
        print(
            f"  [{mark}] {row['id']} expected={row['expected_behavior']} "
            f"got={row['observed_behavior']} phase={row['phase']} steps={row['steps']}"
        )
        if row["issues"]:
            print(f"         issues={row['issues']}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
