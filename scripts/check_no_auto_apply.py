#!/usr/bin/env python3
"""Fail if auto-apply / recruiter-site crawl implementation patterns appear."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("packages", "apps", "scripts")
# Implementation smells — not mere user-facing refusal copy.
PATTERNS = [
    re.compile(r"selenium", re.I),
    re.compile(r"playwright", re.I),
    re.compile(r"boss.*login|login.*boss", re.I),
    re.compile(r"自动投递脚本"),
    re.compile(r"webdriver\.Chrome", re.I),
    re.compile(r"puppeteer", re.I),
]

ALLOW_SUBSTRINGS = (
    "不能协助",
    "禁止",
    "check_no_auto_apply",
    "manual_apply_checklist",
    "人工投递",
    "OUT_OF_SCOPE",
    "out_of_scope",
    "自动投递",  # refusal copy / OOS signals
    "爬虫",  # refusal copy
)


def main() -> int:
    hits: list[str] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".py", ".ts", ".vue", ".js", ".tsx"}:
                continue
            if "node_modules" in path.parts or ".venv" in path.parts:
                continue
            if path.name == "check_no_auto_apply.py":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if any(a in line for a in ALLOW_SUBSTRINGS):
                    continue
                for pat in PATTERNS:
                    if pat.search(line):
                        hits.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()[:120]}")
    if hits:
        print("AUTO-APPLY / CRAWLER PATTERN FOUND:")
        for h in hits:
            print(" ", h)
        return 1
    print("OK: no auto-apply / recruiter crawl implementation patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
