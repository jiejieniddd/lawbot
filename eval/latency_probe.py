"""Offline TTFT probe: python eval/latency_probe.py [--graph-file baseline.py].

Fixed 50ms per synthetic model request; no network or production credentials.
Measures agent TTFT (not HTTP/browser latency). Run baseline and candidate alike.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import statistics
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/lawbot"))
from lawbot.agent import graph
from lawbot.domain.schemas import ChatEvent
from lawbot.llm.client import ProviderCredentials
from lawbot.rag.fake import FakeRetriever


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-file")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    module = graph
    if args.graph_file:
        spec = importlib.util.spec_from_file_location("latency_baseline", args.graph_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    creds = ProviderCredentials(SimpleNamespace(name="offline", provider="openai"), "unused", "offline", None)
    rows = []
    for label, query, fail in [
        ("general_interview", "Python 面试常考什么", False),
        ("clear_backend", "后端面试 Redis 常考什么", False),
        ("short_backend", "后端", False),
        ("stream_failure", "后端面试 Redis 常考什么", True),
    ] * (max(1, args.repeats) + 1):
        calls = {"auxiliary": 0, "stream": 0, "answer_fallback": 0}

        def complete(**kw):
            system = kw.get("system")
            data = {
                module.INTENT_CLASSIFY_SYSTEM_PROMPT: {"intent": "interview_qa"},
                module.CASE_TYPE_CLASSIFY_SYSTEM_PROMPT: {"case_type": "general", "confidence": .9},
                module.FACTS_SUFFICIENCY_SYSTEM_PROMPT: {"facts_sufficient": False, "missing_facts": ["技术栈"], "confirmed_facts": ["意向方向"]},
                module.REWRITE_SYSTEM_PROMPT: {"search_query": query, "user_issue_plain": query},
            }
            calls["auxiliary" if system in data else "answer_fallback"] += 1
            time.sleep(.05)
            return json.dumps(data[system], ensure_ascii=False) if system in data else ""

        def stream(**kw):
            calls["stream"] += 1
            time.sleep(.05)
            if not fail:
                yield "可以从基础知识开始准备。"

        first = None
        with patch.object(module, "complete_text", complete), patch.object(module, "complete_text_stream", stream):
            start = time.perf_counter()
            for event in module.run_agent_stream(query, "offline-probe", credentials=creds, retriever=FakeRetriever(), mock_sleep=0):
                if isinstance(event, ChatEvent) and event.type == "token" and event.data.get("text") and first is None:
                    first = round((time.perf_counter() - start) * 1000, 2)
        rows.append({"case": label, **calls, "ttft_ms": first})
    results = []
    for label in dict.fromkeys(r["case"] for r in rows):
        samples = [r for r in rows if r["case"] == label][1:]  # discard warmup
        results.append({**samples[-1], "ttft_ms": round(statistics.median(r["ttft_ms"] for r in samples), 2)})
    print(json.dumps({"synthetic_request_delay_ms": 50, "repeats": max(1, args.repeats), "aggregation": "median_after_warmup", "results": results}, indent=2))


if __name__ == "__main__":
    main()
