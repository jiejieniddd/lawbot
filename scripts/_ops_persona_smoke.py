"""One-shot ops smoke: CareerBot persona over live /api/v1/chat (UTF-8)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("OPS_API_BASE", "http://127.0.0.1:8000")
PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "Aa@123456")

FORBIDDEN = ("只聚焦中国法域", "我是 LawBot，只", "法律咨询")
REQUIRED_ANY = ("CareerBot", "求职", "面试", "技术")

QUERIES = (
    "你能做什么",
    "大三会 Python，想做后端，面试常考什么",
)


def _load_password() -> str:
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SEED_ADMIN_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return PASSWORD


def _sse_join(raw: str) -> tuple[str, list[dict], list[str]]:
    texts: list[str] = []
    citations: list[dict] = []
    types: list[str] = []
    for block in raw.split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        et = str(ev.get("type") or "")
        types.append(et)
        data = ev.get("data") or {}
        if et == "token" and isinstance(data, dict):
            t = data.get("text")
            if t:
                texts.append(str(t))
        if et == "citation" and isinstance(data, dict):
            citations.append(data)
        if et == "done" and isinstance(data, dict):
            for c in data.get("citations") or []:
                if isinstance(c, dict):
                    citations.append(c)
    return "".join(texts), citations, types


def main() -> int:
    pwd = _load_password()
    rag = ROOT / "data" / "rag_memory" / "records.jsonl"
    rag_lines = 0
    if rag.is_file():
        with rag.open(encoding="utf-8") as f:
            rag_lines = sum(1 for _ in f)

    results: list[dict] = []
    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        login = client.post(
            "/api/admin/auth/login",
            json={"email": "root", "password": pwd},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        ok_all = True
        for q in QUERIES:
            conv = client.post(
                "/api/v1/conversations",
                headers=headers,
                json={"title": f"ops:{q[:20]}"},
            )
            conv.raise_for_status()
            cid = conv.json()["id"]
            with client.stream(
                "POST",
                "/api/v1/chat",
                headers=headers,
                json={"conversation_id": cid, "content": q},
            ) as resp:
                resp.raise_for_status()
                raw = "".join(resp.iter_text())
            joined, cites, _types = _sse_join(raw)
            bad = [f for f in FORBIDDEN if f in joined]
            good = [g for g in REQUIRED_ANY if g in joined]
            source_ids = []
            for c in cites:
                sid = str(c.get("source_id") or "")
                if sid:
                    source_ids.append(sid)
            fake = [s for s in source_ids if s.startswith("fake-")]
            row = {
                "query": q,
                "joined_preview": joined[:280].replace("\n", " "),
                "forbidden_hits": bad,
                "required_hits": good,
                "citation_count": len(source_ids),
                "source_ids_sample": source_ids[:5],
                "fake_source_ids": fake,
                "persona_ok": (not bad) and bool(good),
            }
            results.append(row)
            if not row["persona_ok"]:
                ok_all = False

    out = {
        "api": BASE,
        "rag_memory_lines": rag_lines,
        "all_persona_ok": ok_all,
        "results": results,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
