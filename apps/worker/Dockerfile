FROM python:3.12-slim

WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY packages/lawbot ./packages/lawbot
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

RUN uv sync --all-packages --no-dev --frozen

ENV PATH="/workspace/.venv/bin:$PATH" \
    PYTHONPATH="/workspace/apps/worker"

CMD ["python", "-m", "worker.main"]
