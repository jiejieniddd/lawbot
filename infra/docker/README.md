# infra/docker

Shared Docker/nginx assets for the CareerBot stack.

| File | Used by |
|------|---------|
| `nginx-web.conf` | `apps/web` image (C 端 SPA + `/api` 反代，SSE 关缓冲) |
| `nginx-admin.conf` | `apps/admin` image（后台 SPA + `/api` 反代） |

Primary Dockerfiles live under each `apps/*` package. Root `docker-compose.yml` orchestrates the stack; Python images build with **repo root** context, frontend images also use root context so they can `COPY` these nginx configs.

```bash
# core stack
docker compose up --build

# + Qdrant + OpenSearch + worker
docker compose --profile vectors up --build
```
