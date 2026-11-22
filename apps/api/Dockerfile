FROM python:3.12-slim

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=120

# China ECS: override at build time if needed, e.g. --build-arg UV_INDEX_URL=https://pypi.org/simple
ARG UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV UV_DEFAULT_INDEX=${UV_INDEX_URL}

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

# Workspace members required by uv.lock resolution
COPY pyproject.toml uv.lock ./
COPY packages/lawbot ./packages/lawbot
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

RUN uv sync --all-packages --no-dev --frozen

ENV PATH="/workspace/.venv/bin:$PATH" \
    PYTHONPATH="/workspace/apps/api"

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=20s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["sh", "-c", "cd /workspace/packages/lawbot && alembic -c alembic.ini upgrade head && cd /workspace/apps/api && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
