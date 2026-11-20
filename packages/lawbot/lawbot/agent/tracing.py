"""Structured agent step traces: local JSONL first, Langfuse optional."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._\-]+|api[_-]?key\s*[:=]\s*\S+)"
)
_DEFAULT_TRACE_DIR = Path("data/agent_traces")
_tracer_var: ContextVar["AgentTracer | None"] = ContextVar("agent_tracer", default=None)


def redact_text(value: str | None, *, limit: int = 120) -> str:
    text = _SECRET_RE.sub("[REDACTED]", (value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def privacy_summary(value: str | None, *, limit: int = 120) -> str:
    """Do not store full user text; keep length + short hash + truncated redacted peek."""
    raw = (value or "").strip()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    peek = redact_text(raw, limit=min(40, limit))
    return f"len={len(raw)} hash={digest} peek={peek}"


@dataclass
class TraceStep:
    ts: str
    request_id: str
    conversation_id: str | None
    node: str
    input_summary: str = ""
    output_summary: str = ""
    source_ids: list[str] = field(default_factory=list)
    self_check_issues: list[str] = field(default_factory=list)
    action: str | None = None


class AgentTraceStore:
    def __init__(self, trace_dir: Path | str | None = None) -> None:
        raw = trace_dir or os.environ.get("AGENT_TRACE_DIR") or str(_DEFAULT_TRACE_DIR)
        self.trace_dir = Path(raw)
        self._lock = threading.Lock()

    def path_for(self, request_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", request_id or "unknown")
        return self.trace_dir / f"{safe}.jsonl"

    def append(self, step: TraceStep) -> None:
        path = self.path_for(step.request_id)
        line = json.dumps(asdict(step), ensure_ascii=False)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def load(self, request_id: str) -> list[dict[str, Any]]:
        path = self.path_for(request_id)
        if not path.is_file():
            return []
        steps: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                steps.append(json.loads(line))
        return steps


class _LangfuseBridge:
    """Lazy optional Langfuse. Missing keys or package → no-op."""

    def __init__(self) -> None:
        self._client: Any = None
        self._tried = False

    def _ensure(self) -> Any | None:
        if self._tried:
            return self._client
        self._tried = True
        public_key = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
        secret_key = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
        if not public_key or not secret_key:
            return None
        host = (os.environ.get("LANGFUSE_HOST") or "").strip() or None
        try:
            from langfuse import Langfuse  # type: ignore[import-not-found]
        except Exception:
            logger.info("Langfuse package not installed; local traces only")
            return None
        try:
            kwargs: dict[str, Any] = {
                "public_key": public_key,
                "secret_key": secret_key,
            }
            if host:
                kwargs["host"] = host
            self._client = Langfuse(**kwargs)
        except Exception:
            logger.exception("Langfuse init failed; continuing with local traces")
            self._client = None
        return self._client

    def emit(self, step: TraceStep) -> None:
        client = self._ensure()
        if client is None:
            return
        try:
            client.event(
                name=step.node,
                input={"summary": step.input_summary},
                output={"summary": step.output_summary},
                metadata={
                    "request_id": step.request_id,
                    "conversation_id": step.conversation_id,
                    "source_ids": step.source_ids,
                    "self_check_issues": step.self_check_issues,
                    "action": step.action,
                },
            )
        except Exception:
            logger.exception("Langfuse emit failed for node=%s", step.node)


class AgentTracer:
    def __init__(
        self,
        request_id: str,
        conversation_id: str | None = None,
        *,
        store: AgentTraceStore | None = None,
        langfuse: _LangfuseBridge | None = None,
    ) -> None:
        self.request_id = request_id
        self.conversation_id = conversation_id
        self.store = store or AgentTraceStore()
        self._langfuse = langfuse if langfuse is not None else _LangfuseBridge()

    def step(
        self,
        node: str,
        *,
        input_summary: str = "",
        output_summary: str = "",
        source_ids: list[str] | None = None,
        self_check_issues: list[str] | None = None,
        action: str | None = None,
    ) -> None:
        record = TraceStep(
            ts=datetime.now(timezone.utc).isoformat(),
            request_id=self.request_id,
            conversation_id=self.conversation_id,
            node=node,
            input_summary=redact_text(input_summary),
            output_summary=redact_text(output_summary),
            source_ids=list(source_ids or []),
            self_check_issues=list(self_check_issues or []),
            action=action,
        )
        try:
            self.store.append(record)
        except Exception:
            logger.exception("failed to append local agent trace request_id=%s", self.request_id)
        self._langfuse.emit(record)


def current_tracer() -> AgentTracer | None:
    return _tracer_var.get()


def bind_tracer(tracer: AgentTracer | None):
    return _tracer_var.set(tracer)


def reset_tracer(token) -> None:
    _tracer_var.reset(token)


def trace_step(node: str, **kwargs: Any) -> None:
    tracer = current_tracer()
    if tracer is None:
        return
    tracer.step(node, **kwargs)


def load_trace(request_id: str, trace_dir: Path | str | None = None) -> list[dict[str, Any]]:
    return AgentTraceStore(trace_dir).load(request_id)
