# CareerBot

C 端 **求职 / 面试 / 技术问答** AI Agent + 后台管理。  
工程包名仍为 `lawbot`（`packages/lawbot`、Compose DB 用户等），产品对外统一称 **CareerBot**；**不做**招聘站爬虫与自动投递。

| 目录 | 说明 |
|------|------|
| `apps/api` | FastAPI + JWT + SSE + LangGraph |
| `apps/web` | Vue 3 + Element Plus（C 端） |
| `apps/admin` | React + Ant Design（后台） |
| `apps/worker` | 知识导入：认领 `knowledge_import_jobs` → HF → memory / Qdrant |
| `packages/lawbot` | 共享 domain / db / rag / agent / knowledge |
| `docs/architecture.md` | 架构说明 |

架构：User/Admin → API → LangGraph + Hybrid RRF（`memory` / Qdrant±OpenSearch；空结果空引用，**无 Fake 回退**）+ PostgreSQL + Redis。详见 [docs/architecture.md](docs/architecture.md)。

## 快速开始（Docker Compose 全栈）

```bash
cp .env.example .env
# 必改 JWT_SECRET；生产务必设置独立 ENCRYPTION_KEY（Fernet）
# 勿提交 .env
docker compose up --build
```

一次拉起：**postgres、redis、qdrant、api、worker、web、admin**（默认不含 OpenSearch；低配推荐 `RETRIEVER_MODE=memory`）。

### 本机访问地址（Docker Compose 默认）

浏览器直接打开：

| 用途 | 本机 URL |
|------|----------|
| C 端（用户咨询） | http://localhost:8080 |
| 后台 Admin | http://localhost:8081 |
| API | http://localhost:8000 |
| API Swagger 文档 | http://localhost:8000/docs |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| OpenSearch | http://localhost:9200（需 `docker compose --profile full up`） |

种子超管登录后台：账号 `root`，密码见 `.env` 的 `SEED_ADMIN_PASSWORD`（示例 `Aa@123456`）。

端口由 `.env` 控制（与 `.env.example` 一致）：`WEB_PORT` / `ADMIN_PORT` / `API_PORT` / `POSTGRES_PORT` / `REDIS_PORT`。本机已被占用时改这些变量即可，例如 `API_PORT=8001`、`ADMIN_PORT=8083`，访问地址跟着改成 `http://localhost:<端口>`。

`api` 等待 postgres / redis healthy 与 qdrant started；`web`/`admin` 等待 `api` healthy。前端经 nginx 反代 `/api`。

完整 RAG（Qdrant+OpenSearch hybrid，内存建议 Docker ≥3GB）：

```bash
RETRIEVER_MODE=hybrid EMBEDDING_MODE=auto docker compose --profile full up --build
```

仅基础设施（分端开发）：

```bash
docker compose up postgres redis
```

## 种子账号与角色

| 角色 | 账号 | 密码 | 说明 |
|------|------|------|------|
| `super_admin` | `root`（`SEED_ADMIN_EMAIL`） | `SEED_ADMIN_PASSWORD`（示例 `Aa@123456`） | 唯一超级管理员；不可禁用/删除/降级；可创建普通管理员与 C 端用户 |
| `admin` | 由 root 在后台创建 | — | 可登录后台；可管 C 端用户；**不能**创建管理员 |
| `user` | C 端自助注册，或后台创建 | — | 仅 C 端；不能登录后台 |

C 端用户处置：**禁用**（`user:disable`）为软处理，账号仍在、可再启用；**硬删**（`user:delete`，`super_admin` / `admin`）仅针对 `role=user`，物理删除用户行并由 FK CASCADE 清理会话、消息等，管理员 / operator / 种子超管不可硬删。

C 端登录支持两种**互斥**方式（`POST /api/v1/auth/login` 必填 `mode`）：`password`（邮箱+密码，不验验证码）或 `email_code`（邮箱+6 位验证码，不验密码）。发登录码 `POST /auth/login/send` 仅需邮箱，不再校验密码。同一次登录不会同时强制密码与验证码。后台 Admin 仍为**仅密码**登录。API JSON 字段名仍为 `email`。存量带 `@` 的邮箱账号可登录；种子超管示例：`root`（仅后台）。

## 不对 C 端 / 第三方提供平台 API Key

CareerBot **不提供**平台级对外 `api_keys`、`lb_` Bearer、或「开发者凭证」产品面。

- **C 端**：仅用户注册/登录 JWT（`/api/v1`）
- **模型供应商 Key**：仅 Admin「模型供应商」内部配置，Fernet 加密入库，列表只显示脱敏值
- **禁止**把供应商 Key 暴露给 C 端用户或第三方集成方

## 后台配置模型供应商

1. 打开 Admin http://localhost:8081 ，用种子账号登录  
2. 侧栏 **模型供应商** → 新建：`name`、`provider`、`base_url`（可选）、`api_key`、`default_model`（**预设下拉 + 自定义**，目录见 `GET /api/admin/llm-providers/catalog`）、`priority`、`enabled`  
3. 列表仅见 `api_key_masked`；可启用/禁用、编辑（Key 留空则不改）、删除  
4. 点 **测试连通** → `POST /api/admin/llm-providers/{id}/test` 应返回 `ok: true`（密钥正确且上游可达时）  
5. 对话时选取 **enabled 且 priority 最小** 的供应商经 LiteLLM 调用；若无可用供应商则 **mock 流式**

流式超时（`.env`）：`LLM_TIMEOUT_SECONDS`（默认 60）只约束请求/连接/首包；`LLM_STREAM_IDLE_SECONDS`（默认 120）为 chunk 空闲超时；`LLM_STREAM_MAX_SECONDS`（默认 480）为整段硬顶。空闲/硬顶截断会保留已生成正文并提示可能不完整，不会因整段墙钟静默掐断。

答长：`LLM_ANSWER_MAX_TOKENS`（显式优先）或 `LLM_ANSWER_PROFILE=normal|compact`（normal=1600，compact=800；默认 normal/1600）。仅作用于回答流式，不影响分类短 JSON。提高上限回答更完整，但延迟与成本上升；需要更快首包可改用 `compact` 或更小显式值。若仍触顶，流结束会追加「篇幅受限…」脚注（与超时脚注区分）。

### 法律问答延迟（TTFT）怎么读日志

看 API 日志里的 `agent_timing`：

| 字段 | 含义 |
| --- | --- |
| `intent_ms` / `case_type_ms` / `collect_ms` / `rewrite_ms` + `source=` | 前置；强民生问应为 rule/keyword/heuristic 且接近 0 |
| `retrieve_ms` / `embed_ms` | 检索；BM25 优先，无命中才 embed |
| `graph_ready_ms` | 从请求到 answer/no_basis（prepare）就绪 |
| `time_to_first_token_ms` | 首字；**减去** `graph_ready_ms` ≈ 上游模型 TTFT |
| `answer_stream_ms` | 首字→末字（总生成） |

- **阶段1**：规则短路，减少前置非流式 LLM。
- **阶段2**：prepare 就绪即开流（不必等图 END）；压答长。
- 若 `time_to_first_token_ms - graph_ready_ms` 仍很大：换更低延迟聊天模型、或 `LLM_ANSWER_PROFILE=compact` / 更小 `LLM_ANSWER_MAX_TOKENS`；保证 BM25 有库以减少 embed。代码无法把上游模型「变快」。

样例（FakeRetriever + 模拟上游 sleep 50ms，阶段2 后本地实测）：

| 问句 | 前置 ms / source | retrieve_ms | graph_ready_ms | time_to_first_token_ms | 结论 |
| --- | --- | --- | --- | --- | --- |
| 公司试用期辞退… | 皆 0（rule/keyword/heuristic） | 0 | 22 | 73 | 前置 LLM=0；TTFT−ready≈51ms 为上游 |
| 试用期被辞退…（无「公司」） | 同上 | 0 | 18 | 68 | 当事人槽命中，仍 0 前置 LLM |
| 借条/起诉/时效（欠款） | 同上 | 0 | 20 | 70 | 同上；大头仍在上游模型 |

加密：设置 `.env` 中 `ENCRYPTION_KEY`（Fernet key）。为空时由 `JWT_SECRET` 派生——**生产请使用独立稳定的 ENCRYPTION_KEY**，否则轮换 JWT 会导致无法解密已存 Key。

## CareerBot 知识导入

主库目录：`RAG_MEMORY_DIR`（默认 `data/rag_memory`）。Domain **D** `self_test` 写入 `RAG_SELF_TEST_DIR`（默认 `data/rag_memory_self_test`），**永不**进入 `search_kb`。模拟面试口述题库：`--source mock_interview_zh` → `RAG_MOCK_INTERVIEW_DIR`（默认 `data/rag_memory_mock_interview`，domain=`mock_interview`），**仅** `/api/v1/mock-interview/search` 检索，聊天主库永不混入。

| `--source` | 本地路径（优先） | Domain | 推荐 max_rows | 写入 |
|------------|------------------|--------|---------------|------|
| `interview_zh` | `data/hf/Chinese_interview_large` | `interview_qa` | 200–2000 | 主库 |
| `dev_docs_en` | `data/hf/dev-knowledge-base/data` | `tech_docs` | 500–2000 | 主库 |
| `hive_corpus` | `data/hf/the-hive-corpus` | `gotchas` | 50–500 | 主库 |
| `ai_job_zh` | `data/hf/AI_Job_DataSet_1000_list` | `job_skills` | ≤1000 | 主库 |
| `cmmlu_cs` | `data/hf/cmmlu` | `self_test` | 50–500 | **self_test 隔离** |
| `career_all` | （组合） | A+B+C | 同上分源 | 主库；**不含 D/E** |

```powershell
# 仓库根；.env: RETRIEVER_MODE=memory INDEX_BACKEND=memory EMBEDDING_MODE=fake
# 单源
uv run python scripts/import_career_memory.py --source interview_zh --max-rows 500 --embedding-mode fake
# A+B+C 组合（不含 D self_test / E job_skills）
uv run python scripts/import_career_memory.py --source career_all --max-rows 200 --embedding-mode fake
# 岗位技能地图（非 env；产出 data/market/role_skill_map.json）
uv run python scripts/build_role_skill_map.py
# 重启 api 后加载新索引
cd apps/api; uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Admin → Knowledge → **导入任务**：选择 source（五源）+ `max_rows`；选 `cmmlu_cs` 时自动写入 self_test 目录。Worker 对 `source==cmmlu_cs` 且未显式 `memory_dir` 时同样默认 `RAG_SELF_TEST_DIR`。

- `RETRIEVER_MODE=hybrid`：需本机 Qdrant；OpenSearch 可选（不会 Fake 回退）
- `RETRIEVER_MODE=fake`：仅开发占位（`fake-*` 引用）
- **故意不做：** Boss/招聘站爬虫、自动投递、验证码绕过、FairCV 全量向量化

**免责：** 回复仅供求职/面试参考，不构成录用承诺或法律意见。C 端页脚与 SSE `done.disclaimer` 同口径。

## 总验收 checklist

- [ ] `cp .env.example .env`，设置 `JWT_SECRET`；建议设置独立 `ENCRYPTION_KEY`
- [ ] `docker compose up --build` → web `:8080` / admin `:8081` / api `:8000`
- [ ] Admin 配置供应商 → **测试连通** `ok: true`
- [ ] Career 导入（CLI 或 Admin 五源）→ job `succeeded` → 试检索 / C 端 citation `source_id` 非 `fake-*`
- [ ] C 端免责为职业向；无平台 API Key / `lb_` 入口；普通用户调 `/api/admin/*` → 403
- [ ] `scripts/check_no_auto_apply.py` 通过；`apps/web` / `apps/admin` `npm run typecheck`

## 附录：旧法律/民生导入（兼容，非 CareerBot 主路径）

低配法律样例（遗留）：`scripts/import_local_sample.py` / `import_livelihood_memory.py`；数据集 `senry5433/china-effective-laws-regulations`。民生包按 allow/deny list 过滤后重建 `data/rag_memory`（须 `--recreate`）。CareerBot 请优先用上一节 `import_career_memory.py`。

## 本地开发（分端）

分端 `npm run dev` / `uvicorn` 时的本机地址：

| 用途 | 本机 URL |
|------|----------|
| C 端 Vite | http://localhost:5173 |
| Admin Vite | http://localhost:5174 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

### 1) API

需要：Python 3.12+、[uv](https://docs.astral.sh/uv/)、PostgreSQL、Redis（可用 `docker compose up postgres redis`）。

```bash
uv sync --all-packages
cp .env.example .env
cd packages/lawbot && uv run alembic -c alembic.ini upgrade head
cd ../../apps/api && uv run python -m app.seed
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
uv run pytest apps/api/tests -q
```

### 2) C 端 Web

```bash
cd apps/web
cp .env.example .env   # VITE_API_BASE_URL 本地可留空
npm install && npm run dev   # http://localhost:5173 ，代理 /api → :8000
```

### 3) Admin

```bash
cd apps/admin
cp .env.example .env
npm install && npm run dev   # http://localhost:5174
```

## curl：SSE 与 403

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"myuser","password":"secret12"}' | jq -r .access_token)

CID=$(curl -s -X POST http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | jq -r .id)

curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"conversation_id\":\"$CID\",\"content\":\"劳动合同纠纷咨询\"}"

curl -s http://localhost:8000/api/admin/stats/overview \
  -H "Authorization: Bearer $TOKEN"
# → 403
```

## 接口总表

### 公开 / 基建

- `GET /health`、`GET /ready`

### C 端 `/api/v1`（JWT user）

- `POST /auth/register`、`POST /auth/login`（`mode=password|email_code`，body.`email` 为登录邮箱）、`POST /auth/login/send`（仅邮箱，发登录验证码）、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`、`PATCH /auth/me`（改昵称）、`POST /auth/me/password`（改密码并吊销全部 refresh）
- `POST /auth/me/avatar`（multipart 头像）、`DELETE /auth/me/avatar`；静态访问 `/uploads/avatars/*`
- `POST|GET /conversations`、`GET /conversations/{id}`、`GET /conversations/{id}/messages`
- `POST /chat`（SSE：`token` \| `citation` \| `done` \| `error`；正文为检索增强综合咨询，法条详情见 citation 卡片，正文不做法条清单）。能力边界：聚焦中国法域法律咨询；闲聊可；领域外短拒且不检索。

登录/注册返回 `access_token`（短效）、`refresh_token`（长效）、`token_type`、`expires_in`（秒）。`ACCESS_TOKEN_EXPIRE_MINUTES` 默认 15，`REFRESH_TOKEN_EXPIRE_DAYS` 默认 14。

C 端 Web 个人中心：`/profile`（需登录），可改昵称、改密码、上传/移除头像；改密成功后需重新登录。头像落盘目录由 `UPLOAD_DIR`（默认 `data/uploads/avatars`）控制，单文件上限 `AVATAR_MAX_BYTES`（默认 2MB），仅 jpeg/png/webp；开发经 Vite 代理 `/uploads`，Compose 用 volume `uploads_data` 持久化。

### Admin `/api/admin`（JWT admin / super_admin）

- `POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`
- `GET /stats/overview`
- `GET /users?role=user|admin`（`admin` 含 `super_admin`；可选 `q`）
- `POST /users/admins`（仅 super_admin；固定创建 `admin`）
- `POST /users/clients`（admin/super_admin 创建 `user`）
- `PATCH /users/{id}`（不可禁 root/super_admin；普通 admin 只能改 user；保留至少一名可登录后台账号）
- `GET /conversations`、`GET /conversations/{id}/messages`
- `GET|POST|PATCH|DELETE /knowledge/documents[/{id}]`
- `GET|POST /knowledge/search`（试检索，返回 Citation）
- `GET|POST|PATCH|DELETE /llm-providers[/{id}]`（供应商 Key 加密入库，列表脱敏；`POST .../test`）
- `GET|POST /knowledge-import-jobs`、`GET /knowledge-import-jobs/{id}`（HF 导入；worker 执行）
- `GET /settings`（脱敏）

## CI

GitHub Actions：`.github/workflows/ci.yml`（`uv run pytest`）。前端 typecheck 在本地 checklist 中验证。

## 三层记忆与 thread 契约

| 层 | 作用 | 落点 |
| --- | --- | --- |
| Checkpointer | 同会话短期状态（槽位 / phase / missing） | `thread_id = str(conversation_id)`；Postgres 优先，失败回落 MemorySaver（`production_risk=true`，重启丢槽） |
| 结构化槽位 | `task_goal` / `hard_constraints` / `open_questions` / `key_entities` + 换题清空 | AgentState；续补靠「请补充」或 checkpoint `phase=followup` / missing，不依赖全量 history |
| MemoryStore | 跨会话用户级 top-K（偏好等） | `user_long_memories`；失败只打日志，对话不 500 |

- **同会话**：复用 `conversation_id` → 同一 thread，槽位可续。
- **新咨询**：新建 conversation → 新 thread，短期槽位不串；跨会话 Store 仍可按 `user_id` 注入。
- **Prompt**：系统指令 + 槽位（不裁）+ 最近 N 轮（默认 6，由 chat 从 DB 加载）+ Store top-K + 法条；超预算先丢旧对话再丢低分 Store。
- 删除会话时会尝试 `delete_thread_checkpoints`。Migration：`011_user_long_memories`。
- TODO：>30 轮摘要压缩层尚未实现。

## 已知限制

- 未导入或 `RETRIEVER_MODE=fake` 时：前者 citations 为空；后者才出现 `fake-*`（请改用 memory/hybrid 并导入）
- 不含地方法规；全量约 70 万条勿在低配机跑；小样本用 `IMPORT_MAX_ROWS=100–200`
- SSE 无断线续传；未上 K8s
- >30 轮对话摘要压缩未做（槽位 + 最近 N + Store 已落地）

## Eval

`python eval/run_eval.py`（金标 15 条，报告写入 `eval/last_report.json`）。

## 后续可选

地方法规入库、全量导入运维、SSE 重连、律师审核工单。

---

**会话 5/5 完成（五会话收口）。**
