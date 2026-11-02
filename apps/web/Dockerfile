# Build context: repository root (see docker-compose.yml)
FROM node:22-alpine AS build
WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY apps/web/ ./
ARG VITE_API_BASE_URL=
ARG VITE_API_BASE=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL:-$VITE_API_BASE}
RUN npm run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx-web.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ || exit 1
