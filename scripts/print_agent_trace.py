#!/usr/bin/env python3
"""Print a local agent JSONL trace by request_id.

Usage (repo root):
  python scripts/print_agent_trace.py <request_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages" / "lawbot") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.agent.tracing import AgentTraceStore  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/print_agent_trace.py <request_id>", file=sys.stderr)
        return 2
    request_id = argv[1]
    steps = AgentTraceStore().load(request_id)
    if not steps:
        print(f"No trace for request_id={request_id}", file=sys.stderr)
        return 1
    print(json.dumps({"request_id": request_id, "steps": steps}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
