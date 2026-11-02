# LawBot Web（C 端）

Vue 3 + TypeScript + Vite + Vue Router + Pinia + Element Plus。

**仅 JWT 用户体系。** 无 API Key / 开发者凭证 / `lb_` 入口；模型供应商 Key 仅在 Admin（会话 4）。

## 前置

先启动 API（默认 `http://localhost:8000`），参见仓库根目录 README。

## 启动

```bash
cd apps/web
cp .env.example .env   # 可选；本地开发可留空 VITE_API_BASE_URL
npm install
npm run dev
# http://localhost:5173 — Vite 已将 /api、/health 代理到 :8000
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `VITE_API_BASE_URL` | API 根地址。本地开发留空则走代理；生产可设为 `https://api.example.com` |
| `VITE_API_BASE` | 旧名，仍兼容作为 fallback |

## 脚本

```bash
npm run typecheck   # vue-tsc
npm run build       # typecheck + vite build
npm run preview
```

## 能力

- 注册 / 登录（已登录访问 auth 页会重定向 `/chat`）
- 会话列表、新建、切换；`POST /api/v1/chat` SSE（`token` / `citation` / `done` / `error`）
- Citation 卡片：law_name、article_no、text、source_id（流式边收边显）
- 免责：非正式法律意见 + 数据集非国家官方汇编
- HTTP 401 → 自动 refresh 一次后重试；失败则清双 token 并跳转登录

## 验收路径

注册 → 登录 → 新建/切换会话 → 发消息 → SSE 流式回复 + citation 卡片 → 页脚免责含「非官方」→ 刷新后历史仍在 → 退出需重新登录。
