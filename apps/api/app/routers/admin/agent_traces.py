from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.deps import require_permission
from lawbot.agent.tracing import AgentTraceStore
from lawbot.db.models import User

router = APIRouter(prefix="/agent-traces", tags=["admin-agent-traces"])


@router.get("/{request_id}")
def get_agent_trace(
    request_id: str,
    _: User = Depends(require_permission("audit:read")),
) -> dict:
    settings = get_settings()
    steps = AgentTraceStore(settings.agent_trace_dir).load(request_id)
    if not steps:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    return {"request_id": request_id, "steps": steps}
