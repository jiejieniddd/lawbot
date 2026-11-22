# CareerBot Admin

React + TypeScript + Vite + React Router + Ant Design + TanStack Query。

**供应商密钥**经「模型供应商」页写入 `/api/admin/llm-providers`（`ENCRYPTION_KEY` Fernet 加密，列表仅 `api_key_masked`）。  
**无**平台对外 API Key / `lb_` / 开发者凭证页面。详见仓库根 [README](../../README.md)。

## 前置

先启动 API（全栈：`docker compose up --build`，或本地 uvicorn）。唯一超管 `root`（`SEED_ADMIN_*`，role=`super_admin`）由 seed 写入。

| 字段 | 值 |
|------|-----|
| Email/账号 | `root` |
| Password | `Aa@123456`（见仓库 `.env.example`） |

## 启动

```bash
cd apps/admin
cp .env.example .env   # VITE_API_BASE_URL 本地可留空（走 Vite 代理）
npm install
npm run dev
# http://localhost:5174 — /api 代理到 :8000
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `VITE_API_BASE_URL` | API 根地址；本地留空走代理 |
| `VITE_API_BASE` | 旧名，兼容 fallback |

## 脚本

```bash
npm run typecheck
npm run build
npm run preview
```

## 页面

- Dashboard：`/api/admin/stats/overview`
- **C端用户** `/users/clients`：列表 +「新建用户」；禁用开关、账号搜索  
- **管理员** `/users/admins`：展示超级/普通管理员；仅 root 可「新建普通管理员」；不可禁 root  
- Audit：会话 → 消息与 citations
- **模型供应商**：CRUD、启用开关、脱敏 key、测试连通；Default Model 支持**预设下拉 + 自定义**（目录 `GET /api/admin/llm-providers/catalog`，失败回退本地常量）
- Knowledge：文档 CRUD / 导入任务（轮询）/ 试检索
- Settings：脱敏只读配置

## 验收（与根 README 总验收对齐）

1. 登录 → 模型供应商：新建 / 编辑 / 禁用 / 删除 / 测试连通 `ok`；列表仅脱敏 key  
2. Knowledge → 触发导入、试检索；citation `source_id` 非 `fake-*`（导入成功后）  
3. 全站无「平台 API Key」入口或文案  

401（除登录/refresh 外）会单飞 refresh 后重试；失败或 403 则清双 token 并跳转登录页。
