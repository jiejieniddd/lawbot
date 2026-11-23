from __future__ import annotations

import uuid
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.received_at = time.monotonic()
        supplied = request.headers.get("x-request-id") or ""
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
