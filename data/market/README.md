# Market skill map (CareerBot Phase3)

- `role_skill_map.json` is built by `scripts/build_role_skill_map.py`.
- Primary source: Domain E (`job_skills`) records in `data/rag_memory`.
- FairCV / Job-SDF: optional local sample under `data/hf/faircv_sample`, **max 50 rows**, skills aggregation only — **never** full-vectorized into RAG.
