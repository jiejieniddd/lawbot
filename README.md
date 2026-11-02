# LawBot

C 端法律咨询 AI Agent + 后台管理（生产形态骨架）。

| 目录 | 说明 |
|------|------|
| `apps/api` | FastAPI + JWT + SSE + LangGraph |
| `apps/web` | Vue 3 + Element Plus（C 端） |
| `apps/admin` | React + Ant Design（后台） |
| `apps/worker` | 知识导入：认领 `knowledge_import_jobs` → HF → Qdrant+OpenSearch |
| `packages/lawbot` | 共享 domain / db / rag / agent / knowledge |
| `docs/architecture.md` | 架构说明 |

架构要点：User/Admin → API → LangGraph + Hybrid RRF（Qdrant+OpenSearch，失败回退 FakeRetriever）+ PostgreSQL + Redis。详见 [docs/architecture.md](docs/architecture.md)。

## 快速开始（Docker Compose 全栈）

```bash
cp .env.example .env
# 必改 JWT_SECRET；生产务必设置独立 ENCRYPTION_KEY（Fernet）
# 勿提交 .env
docker compose up --build
```

一次拉起：**postgres、redis、qdrant、opensearch、api、worker、web、admin**。

| 服务 | URL / 端口 |
|------|------------|
| C 端 Web | http://localhost:8080 |
| Admin | http://localhost:8081 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Qdrant | http://localhost:6333 |
| OpenSearch | http://localhost:9200 |
| Worker | 后台轮询导入任务（无对外端口） |

`api` 等待 postgres / redis / opensearch healthy 与 qdrant started；`web`/`admin` 等待 `api` healthy。前端经 nginx 反代 `/api`。

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

后台登录为账号+密码（字段名仍为 `email`，允许非邮箱账号如 `root`）。

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

## HF 法规数据集导入与免责

**步骤：**

1. `docker compose up --build`（含 worker + Qdrant + OpenSearch）  
2. Admin → Knowledge → **导入任务** → 设置 `max_rows`（默认环境 `IMPORT_MAX_ROWS=500`，`0`=不截断）→ 触发导入  
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
npm install && npm run dev   # :5173，代理 /api → :8000
```

### 3) Admin

```bash
cd apps/admin
cp .env.example .env
npm install && npm run dev   # :5174
```

## curl：SSE 与 403

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"secret12"}' | jq -r .access_token)

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

- `POST /auth/register`、`POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`
- `POST|GET /conversations`、`GET /conversations/{id}`、`GET /conversations/{id}/messages`
- `POST /chat`（SSE：`token` \| `citation` \| `done` \| `error`）

登录/注册返回 `access_token`（短效）、`refresh_token`（长效）、`token_type`、`expires_in`（秒）。`ACCESS_TOKEN_EXPIRE_MINUTES` 默认 15，`REFRESH_TOKEN_EXPIRE_DAYS` 默认 14。

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

- 未导入完成前引用可能仍为 FakeRetriever（`fake-*`）
- 不含地方法规；全量约 70 万条需调大/取消 `IMPORT_MAX_ROWS`（注意机器内存，OpenSearch 默认 JVM 512m）
- SSE 无断线续传；未上 K8s

## 后续可选

地方法规入库、全量导入运维、`eval/` 金标扩充、SSE 重连、律师审核工单。

---

**会话 5/5 完成（五会话收口）。**
