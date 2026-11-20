# LawBot

C 端法律咨询 AI Agent + 后台管理（生产形态骨架）。

| 目录 | 说明 |
|------|------|
| `apps/api` | FastAPI + JWT + SSE + LangGraph |
| `apps/web` | Vue 3 + Element Plus（C 端） |
| `apps/admin` | React + Ant Design（后台） |
| `apps/worker` | 知识导入：认领 `knowledge_import_jobs` → HF → memory 落盘或 Qdrant（OpenSearch 可选） |
| `packages/lawbot` | 共享 domain / db / rag / agent / knowledge |
| `docs/architecture.md` | 架构说明 |

架构要点：User/Admin → API → LangGraph + Hybrid RRF（`memory` / Qdrant±OpenSearch；空结果返回空引用，**不再 Fake 回退**）+ PostgreSQL + Redis。详见 [docs/architecture.md](docs/architecture.md)。

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

C 端与后台均为**账号+密码**登录（API JSON 字段名仍为 `email`，存的是登录账号）。新注册账号规则：3–32 位小写字母/数字/下划线（如 `myuser`）；存量带 `@` 的老账号仍可登录。种子超管示例：`root`。

## 不对 C 端 / 第三方提供平台 API Key

LawBot **不提供**平台级对外 `api_keys`、`lb_` Bearer、或「开发者凭证」产品面。

- **C 端**：仅用户注册/登录 JWT（`/api/v1`）
- **模型供应商 Key**：仅 Admin「模型供应商」内部配置，Fernet 加密入库，列表只显示脱敏值
- **禁止**把供应商 Key 暴露给 C 端用户或第三方集成方

## 后台配置模型供应商

1. 打开 Admin http://localhost:8081 ，用种子账号登录  
2. 侧栏 **模型供应商** → 新建：`name`、`provider`、`base_url`（可选）、`api_key`、`default_model`（**预设下拉 + 自定义**，目录见 `GET /api/admin/llm-providers/catalog`）、`priority`、`enabled`  
3. 列表仅见 `api_key_masked`；可启用/禁用、编辑（Key 留空则不改）、删除  
4. 点 **测试连通** → `POST /api/admin/llm-providers/{id}/test` 应返回 `ok: true`（密钥正确且上游可达时）  
5. 对话时选取 **enabled 且 priority 最小** 的供应商经 LiteLLM 调用；若无可用供应商则 **mock 流式**

加密：设置 `.env` 中 `ENCRYPTION_KEY`（Fernet key）。为空时由 `JWT_SECRET` 派生——**生产请使用独立稳定的 ENCRYPTION_KEY**，否则轮换 JWT 会导致无法解密已存 Key。

## 低配启用真实检索（推荐，无需 OpenSearch）

目标：法律问题引用的 `source_id` **不是** `fake-*`；无命中则无引用卡片，由**已配置的 LLM**贴题作答（勿用 `hybrid` 空库硬顶）。适合 **Windows + 仅本机 `uv run` api**，不必 `docker compose --profile full`。

**验收步骤（可复制）：**

```powershell
# 在仓库根目录；先准备 .env（可从 .env.example 复制）
# 必填低配项：
# RETRIEVER_MODE=memory
# INDEX_BACKEND=memory
# RAG_MEMORY_DIR=data/rag_memory
# IMPORT_MAX_ROWS=200
# EMBEDDING_MODE=fake
# HF_DATASET_ID=senry5433/china-effective-laws-regulations

# 1) 小样本导入到落盘索引（约 100–200 条即可，勿全量）
uv run python scripts/import_local_sample.py --max-rows 200 --backend memory

# 2) 启动 / 重启 api（必须重启才能加载 data/rag_memory）
cd apps/api
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3) Admin 试检索「劳动合同」→ source_id 非 fake-*
# 4) C 端法律问题 → 有真实引用，或空引用 + 真模型贴题回答（需 Admin 已启用供应商）
```

可选离线数据集：

```powershell
huggingface-cli download senry5433/china-effective-laws-regulations --repo-type dataset --local-dir data/hf/china-laws
# .env: HF_DATASET_ID=data/hf/china-laws  以及 HF_DATASETS_OFFLINE=1
```

- `RETRIEVER_MODE=hybrid`：需本机 Qdrant 且已导入；OpenSearch 可选（挂了则仅向量，不会 Fake 回退）
- `RETRIEVER_MODE=fake`：仅开发占位，会出现 `fake-*`，不要当真实知识库
- 已配置模型时：空检索走真模型「未检索到」约束作答，不再塞「合同、转账」跑题模拟稿

## HF 法规数据集导入与免责

**步骤：**

1. `docker compose up --build`（默认不含 OpenSearch；完整 RAG 用 `--profile full`）  
2. Admin → Knowledge → **导入任务** → 设置 `max_rows`（默认环境 `IMPORT_MAX_ROWS=200`，`0`=不截断）→ 触发导入  
   或：

```bash
curl -s -X POST http://localhost:8000/api/admin/knowledge-import-jobs \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{}'
```

3. Worker 认领 `pending` → 过滤/chunk/嵌入 → 双写 Qdrant+OpenSearch → `succeeded` + `stats`  
4. Admin **试检索** 或 C 端发问，citation 的 `source_id` 应为真实条目 id（**非** `fake-*`）

**数据范围：** HF `senry5433/china-effective-laws-regulations` / `articles`；`status==有效` 且 `category ∈ {法律, 行政法规, 司法解释}`；chunk：`《{title}》{article_no_cn} {text}`。

**免责：** 回复仅供参考，不构成正式法律意见。检索依据的法规条文来自**第三方整理的数据集，非国家官方汇编、非权威发布渠道**，请以全国人大等官方来源为准。C 端页脚与 SSE `done.disclaimer` 含同口径说明。

## 总验收 checklist

- [ ] `cp .env.example .env`，设置 `JWT_SECRET`；建议设置独立 `ENCRYPTION_KEY`
- [ ] `docker compose up --build` → web `:8080` / admin `:8081` / api `:8000`；Qdrant/OpenSearch/worker 均已启动
- [ ] Admin 配置供应商 → **测试连通** `ok: true`（或对话明确走配置模型、非 mock）
- [ ] 触发 HF 小样本导入 → job `succeeded` → 试检索 / C 端 SSE citation 含 `law_name`、`article_no`、`text`、`source_id`，且 **`source_id` 非 `fake-*`**
- [ ] C 端免责含数据集非官方说明；无平台 API Key / `lb_` / 开发者凭证入口
- [ ] 普通用户 token 调 `/api/admin/*` → 403
- [ ] `uv run pytest apps/api/tests -q`；`apps/web` 与 `apps/admin` 下 `npm run typecheck` 通过

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

- `POST /auth/register`、`POST /auth/login`（body.`email` 为登录账号）、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`、`PATCH /auth/me`（改昵称）、`POST /auth/me/password`（改密码并吊销全部 refresh）
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

## 已知限制

- 未导入或 `RETRIEVER_MODE=fake` 时：前者 citations 为空；后者才出现 `fake-*`（请改用 memory/hybrid 并导入）
- 不含地方法规；全量约 70 万条勿在低配机跑；小样本用 `IMPORT_MAX_ROWS=100–200`
- SSE 无断线续传；未上 K8s

## Eval

`python eval/run_eval.py`（金标 15 条，报告写入 `eval/last_report.json`）。

## 后续可选

地方法规入库、全量导入运维、SSE 重连、律师审核工单。

---

**会话 5/5 完成（五会话收口）。**
