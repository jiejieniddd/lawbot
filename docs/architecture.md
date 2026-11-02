# LawBot Architecture

## System responsibilities

| Component | Responsibility |
|-----------|----------------|
| `apps/web` | C 端：JWT 注册登录、会话、SSE、CitationCard、免责（含数据集非官方）；无 API Key UI |
| `apps/admin` | 后台：统计、用户禁用、会话审计、模型供应商 CRUD、知识导入/试检索、脱敏设置；无平台 API Key UI |
| `apps/api` | 统一 FastAPI：JWT、业务 API、SSE、种子与健康检查 |
| `apps/worker` | 认领 `knowledge_import_jobs`，HF 过滤/chunk，双写 Qdrant+OpenSearch |
| `packages/lawbot` | 共享 domain / SQLAlchemy+Alembic / Hybrid RAG / LangGraph / knowledge |
| PostgreSQL | 用户、会话、消息（含 citations）、知识文档元数据、导入任务、LLM 供应商 |
| Redis | `/ready` 探测；限流/缓存占位 |
| Qdrant | 法规向量检索（compose 默认启动） |
| OpenSearch | 法规 BM25 检索（compose 默认启动） |

## Mermaid overview

```mermaid
flowchart LR
  user[C_end_User] --> web[apps_web]
  adminUser[Admin_User] --> admin[apps_admin]
  web -->|JWT_user_/api/v1| api[apps_api]
  admin -->|JWT_admin_/api/admin| api
  api --> graph[LangGraph]
  graph --> hybrid[Hybrid_RRF]
  hybrid --> qdrant[(Qdrant)]
  hybrid --> os[(OpenSearch)]
  hybrid -->|down| fake[FakeRetriever]
  admin -->|create_job| jobs[(knowledge_import_jobs)]
  worker[apps_worker] --> jobs
  worker --> hf[HF_articles]
  worker --> qdrant
  worker --> os
  api --> db[(PostgreSQL)]
  api --> redis[(Redis)]
```

## Roles and route prefixes

| Role | How obtained | Allowed prefixes |
|------|----------------|------------------|
| anonymous | — | `POST /api/v1/auth/register\|login`, `POST /api/admin/auth/login`, `/health`, `/ready` |
| `user` | C 端注册/登录 JWT | `/api/v1/*`（本人会话）；访问 `/api/admin/*` → **403** |
| `admin` | 种子或库内 `role=admin` | `/api/admin/*`；也可持有 user 能力若走 C 端 API |

JWT claim：`sub`, `email`, `role`. Disabled users：login / authenticated calls → 403.

**No platform API Key:** 不对 C 端或第三方发放 `api_keys` / `lb_`；供应商密钥仅 Admin 内部、Fernet（`ENCRYPTION_KEY`）加密。

## Agent / RAG

```
classify → collect → retrieve(Hybrid RRF) → answer(stream) → guardrail
```

- Vector：Qdrant collection `lawbot_articles_v1`
- Lexical：OpenSearch index `lawbot_articles_v1`
- Fusion：Reciprocal Rank Fusion；任一侧失败/空结果则另一侧仍可用；两侧皆空 → FakeRetriever
- `RETRIEVER_MODE=hybrid|fake|memory`

SSE：`token` | `citation` | `done` | `error`（`guardrail_blocked`）。

C 端仅 JWT；`CitationCard` 展示 law_name、article_no、text、source_id；免责含「第三方数据集非国家官方汇编」。

## Compose

`docker compose up --build` 默认拉起：postgres、redis、qdrant、opensearch、api、worker、web、admin。  
容器内 `QDRANT_URL` / `OPENSEARCH_URL` / `DATABASE_URL` 使用服务名，不继承宿主机 `.env` 的 localhost。  
`web`/`admin` nginx 将 `/api` 反代到 `api:8000`。

## Knowledge import

1. Admin `POST /api/admin/knowledge-import-jobs`（默认 HF source；`config.max_rows` ← `IMPORT_MAX_ROWS`）
2. Worker：`pending` → `running` → 流式过滤/嵌入/upsert → `stats` + `succeeded|failed`
3. Filter：`status==有效` 且 `category ∈ {法律, 行政法规, 司法解释}`
4. Chunk：`《{title}》{article_no_cn} {text}`；`source_id` ← HF `id`

## Data model (summary)

- `users` — email, password_hash, role, disabled  
- `conversations` — user_id, title, status  
- `messages` — role, content, citations JSONB, request_id  
- `knowledge_documents` — title, status, meta JSONB, updated_at  
- `llm_providers` — supplier config; `api_key_encrypted` (Fernet / `ENCRYPTION_KEY`); priority/enabled  
- `knowledge_import_jobs` — status, source, config, stats, error  

**Not in schema:** platform `api_keys` / public `lb_` bearer tokens.

## LLM path

Admin configures providers → encrypted in PG → chat picks enabled + lowest priority → LiteLLM → SSE tokens.  
`POST /api/admin/llm-providers/{id}/test` 用于连通验收。  
If none enabled → mock answer stream + log.

## Admin UI

- `/providers` — 模型供应商（`api_key_masked`；测试连通）
- `/knowledge` — 文档 / 导入任务 / 试检索
- **Not present:** 平台 `api_keys` / `lb_` / 开发者凭证页

## Out of scope

地方法规入库、平台 API Key、全量强制导入、K8s、支付/短信、多租户 RBAC。

## Optional next

eval 金标扩充、全量导入运维、SSE 重连、可观测性增强。
