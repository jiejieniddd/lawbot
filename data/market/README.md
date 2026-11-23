# CareerBot computer-career knowledge

- `scripts/build_computing_memory.py` reads the existing memory index, retains its computer-related records, removes generic interview questions, and adds 33 computer occupation profiles. It writes a separate index for review before activation. The reviewed index is active locally at `data/rag_memory`; the previous 2,805-record index is preserved at `data/rag_memory.bak_20261123_computing`.
- The source is the **O*NET 31.0 Database**, U.S. Department of Labor, Employment and Training Administration: <https://www.onetcenter.org/database.html>. O*NET data is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). CareerBot adds Chinese search aliases and curated skill lists; these are not O*NET's translations or official recommendations.
- Local O*NET downloads reside under ignored `data/hf/onet_31_0`. Required files: `occupation_data.json` and `software_skills.csv`. The built memory indexes are also ignored by Git; upload `records.jsonl` and `vectors.json` separately when deploying.
- `scripts/build_role_skill_map.py --memory-dir data/rag_memory --faircv-sample 0` builds the tracked `role_skill_map.json`. Specialized aliases in `computing_role_skill_overrides.json` take precedence over broad O*NET occupation examples.
- `scripts/check_computing_retrieval.py --memory-dir data/rag_memory` checks six representative roles through the same retrieval stage used by chat.
- FairCV / Job-SDF remain optional local samples for skill aggregation only. They are not embedded into the memory index.

The reviewed local build had 2,175 records: 1,033 job skills, 137 technical interview questions, 1,000 developer documents, and 5 troubleshooting notes. It excluded 663 generic interview records from the previous 2,805-record index. This is a curated computing-career index; individual company requirements still depend on the job description.
