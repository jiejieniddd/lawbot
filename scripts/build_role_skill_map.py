#!/usr/bin/env python3
"""Build data/market/role_skill_map.json from Domain E (+ optional FairCV sample).

FairCV / Job-SDF are NEVER fully embedded. If a local FairCV/Job-SDF sample exists,
at most --faircv-sample rows are read for skill aggregation only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages" / "lawbot") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))


def _normalize_role(title: str) -> str:
    t = (title or "").strip()
    t = re.sub(r"[【\[].*?[】\]]", "", t)
    t = re.sub(r"\s+", "", t)
    for key in (
        "算法工程师",
        "后端工程师",
        "前端工程师",
        "深度学习",
        "机器学习",
        "SLAM",
        "视觉",
        "NLP",
        "大模型",
        "AIGC",
        "数据科学",
        "推荐",
        "搜索",
        "运维",
        "DevOps",
    ):
        if key.lower() in t.lower() or key in t:
            return key
    return t[:24] or "通用算法"


def _skills_from_record(row: dict) -> list[str]:
    skills = row.get("skills") or (row.get("meta") or {}).get("skills") or []
    out: list[str] = []
    if isinstance(skills, list):
        for s in skills:
            s = str(s).strip()
            if s and s not in out:
                out.append(s)
    return out


def _load_job_skills_from_memory(memory_dir: Path) -> list[tuple[str, list[str]]]:
    path = memory_dir / "records.jsonl"
    if not path.is_file():
        return []
    rows: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("domain") or "") != "job_skills":
            continue
        title = str(row.get("title") or row.get("law_name") or "")
        skills = _skills_from_record(row)
        if not skills:
            # fallback parse from chunk_text "title | skills | duty"
            chunk = str(row.get("chunk_text") or "")
            parts = [p.strip() for p in chunk.split("|")]
            if len(parts) >= 2 and parts[1] and parts[1] != "（未标注）":
                skills = [x.strip() for x in re.split(r"[、,/，]", parts[1]) if x.strip()]
        aliases = (row.get("meta") or {}).get("zh_aliases") or []
        if row.get("source_name") == "onet_31_0" and isinstance(aliases, list):
            rows.extend((str(alias).strip(), skills) for alias in aliases if str(alias).strip())
        else:
            rows.append((_normalize_role(title), skills))
    return rows


def _load_faircv_sample(path: Path, *, limit: int) -> list[tuple[str, list[str]]]:
    """Optional FairCV/Job-SDF local sample — skills aggregation only, never embedded."""
    if not path.exists() or limit <= 0:
        return []
    out: list[tuple[str, list[str]]] = []
    files: list[Path] = []
    if path.is_file():
        files = [path]
    else:
        files = sorted(path.glob("**/*.{jsonl,json,csv}".replace("{", "").replace("}", "")))
        files = sorted(list(path.glob("**/*.jsonl")) + list(path.glob("**/*.json")))[:5]
    for fp in files:
        try:
            if fp.suffix.lower() == ".jsonl":
                for line in fp.read_text(encoding="utf-8-sig").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    title = str(row.get("title") or row.get("job_title") or row.get("role") or "")
                    skills = row.get("skills") or row.get("skill_list") or []
                    if isinstance(skills, str):
                        skills = [s.strip() for s in re.split(r"[,，、]", skills) if s.strip()]
                    out.append((_normalize_role(title), list(skills) if isinstance(skills, list) else []))
                    if len(out) >= limit:
                        return out
            elif fp.suffix.lower() == ".json":
                raw = json.loads(fp.read_text(encoding="utf-8-sig"))
                items = raw if isinstance(raw, list) else raw.get("data") or []
                for row in items:
                    if not isinstance(row, dict):
                        continue
                    title = str(row.get("title") or row.get("job_title") or "")
                    skills = row.get("skills") or []
                    out.append((_normalize_role(title), list(skills) if isinstance(skills, list) else []))
                    if len(out) >= limit:
                        return out
        except Exception as exc:
            print(f"skip faircv file {fp}: {exc}")
    return out[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", default="data/rag_memory")
    parser.add_argument("--out", default="data/market/role_skill_map.json")
    parser.add_argument("--faircv-path", default="data/hf/faircv_sample")
    parser.add_argument("--faircv-sample", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    if not memory_dir.is_absolute():
        memory_dir = ROOT / memory_dir
    pairs = _load_job_skills_from_memory(memory_dir)
    faircv_path = Path(args.faircv_path)
    if not faircv_path.is_absolute():
        faircv_path = ROOT / faircv_path
    faircv_pairs = _load_faircv_sample(faircv_path, limit=args.faircv_sample)
    if faircv_pairs:
        print(
            f"FairCV/Job-SDF: sampled {len(faircv_pairs)} rows for skill aggregation ONLY "
            f"(NOT embedded into rag_memory)"
        )
    else:
        print("FairCV/Job-SDF: no local sample; map built from Domain E only (no full embed)")

    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for role, skills in pairs + faircv_pairs:
        if not role:
            continue
        for s in skills:
            s = str(s).strip()
            if s and s != "（未标注）":
                buckets[role][s] += 1

    mapping = {
        role: [s for s, _n in counter.most_common(args.top_k)]
        for role, counter in sorted(buckets.items(), key=lambda x: (-sum(x[1].values()), x[0]))
        if counter
    }
    # O*NET's broad occupation skills do not distinguish a Java fullstack role
    # from iOS or frontend specializations. Explicit CareerBot lists do.
    overrides_path = ROOT / "data/market/computing_role_skill_overrides.json"
    if overrides_path.is_file():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        for role, skills in overrides.items():
            mapping[role] = skills[: args.top_k]
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "source": "job_skills (including O*NET 31.0) + CareerBot role-specific overrides + optional FairCV sample",
        "faircv_embedded": False,
        "roles": mapping,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} roles={len(mapping)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
