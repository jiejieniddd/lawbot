"""Smoke after Career RAG rebuild: persona + citation domains (UTF-8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

QUERIES = (
    "大三会 Python，想做后端，就业方向和校招要什么技能",
    "Python 后端面试 Redis 常考什么",
)

FORBIDDEN = ("只聚焦中国法域", "我是 LawBot，只", "法律咨询", "音乐播放器", "微博运营")


def _password() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_ADMIN_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"')
    return "Aa@123456"


def _sse_join(raw: str) -> tuple[str, list[dict]]:
    texts: list[str] = []
    cites: list[dict] = []
    for block in raw.split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        et = str(ev.get("type") or "")
        data = ev.get("data") or {}
        if et == "token" and isinstance(data, dict) and data.get("text"):
            texts.append(str(data["text"]))
        if et == "citation" and isinstance(data, dict):
            cites.append(data)
        if et == "done" and isinstance(data, dict):
            for c in data.get("citations") or []:
                if isinstance(c, dict):
                    cites.append(c)
    return "".join(texts), cites


def main() -> int:
    pwd = _password()
    rows = []
    ok = True
    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        token = client.post(
            "/api/admin/auth/login",
            json={"email": "root", "password": pwd},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for q in QUERIES:
            cid = client.post(
                "/api/v1/conversations",
                headers=headers,
                json={"title": f"rag:{q[:16]}"},
            ).json()["id"]
            with client.stream(
                "POST",
                "/api/v1/chat",
                headers=headers,
                json={"conversation_id": cid, "content": q},
            ) as resp:
                resp.raise_for_status()
                raw = "".join(resp.iter_text())
            joined, cites = _sse_join(raw)
            domains = [str(c.get("domain") or "") for c in cites]
            sids = [str(c.get("source_id") or "") for c in cites]
            bad = [f for f in FORBIDDEN if f in joined]
            careerish = any(x in joined for x in ("CareerBot", "求职", "面试", "技能", "后端"))
            row = {
                "query": q,
                "preview": joined[:300].replace("\n", " "),
                "forbidden": bad,
                "careerish": careerish,
                "domains": domains,
                "source_ids": sids[:6],
                "has_ai_job": any(s.startswith("ai_job:") for s in sids),
                "has_fake": any(s.startswith("fake-") for s in sids),
            }
            rows.append(row)
            if bad or not careerish or row["has_fake"]:
                ok = False
            if "就业方向" in q or "校招要什么" in q:
                # Prefer job_skills / ai_job for career direction
                if sids and not row["has_ai_job"] and "job_skills" not in domains:
                    row["warn"] = "career_advice citations not job_skills-first"
                    # soft fail warning only if all interview soft noise
                    if any("微博" in (c.get("law_name") or "") for c in cites):
                        ok = False

    print(json.dumps({"ok": ok, "results": rows}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
