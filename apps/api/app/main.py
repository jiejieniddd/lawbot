from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.middleware import RequestIdMiddleware
from app.routers import health
from app.routers.admin import auth as admin_auth
from app.routers.admin import conversations as admin_conversations
from app.routers.admin import knowledge as admin_knowledge
from app.routers.admin import knowledge_jobs as admin_knowledge_jobs
from app.routers.admin import knowledge_search as admin_knowledge_search
from app.routers.admin import llm_providers as admin_llm_providers
from app.routers.admin import roles as admin_roles
from app.routers.admin import settings as admin_settings
from app.routers.admin import stats as admin_stats
from app.routers.admin import users as admin_users
from app.routers.v1 import auth as v1_auth
from app.routers.v1 import chat as v1_chat
from app.routers.v1 import conversations as v1_conversations
from app.services.avatars import resolve_upload_dir, uploads_static_root

settings = get_settings()
resolve_upload_dir(settings)
uploads_root = uploads_static_root(settings)
uploads_root.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="LawBot API", version="0.1.0")
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(v1_auth.router, prefix="/api/v1")
app.include_router(v1_conversations.router, prefix="/api/v1")
app.include_router(v1_chat.router, prefix="/api/v1")
app.include_router(admin_auth.router, prefix="/api/admin")
app.include_router(admin_stats.router, prefix="/api/admin")
app.include_router(admin_users.router, prefix="/api/admin")
app.include_router(admin_roles.router, prefix="/api/admin")
app.include_router(admin_conversations.router, prefix="/api/admin")
app.include_router(admin_knowledge.router, prefix="/api/admin")
app.include_router(admin_knowledge_search.router, prefix="/api/admin")
app.include_router(admin_knowledge_jobs.router, prefix="/api/admin")
app.include_router(admin_llm_providers.router, prefix="/api/admin")
app.include_router(admin_settings.router, prefix="/api/admin")
app.mount("/uploads", StaticFiles(directory=str(uploads_root)), name="uploads")


def _error_body(request: Request, detail: str, code: str | None = None, status_code: int = 400) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    body: dict = {"detail": detail, "request_id": request_id}
    if code:
        body["code"] = code
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return _error_body(request, detail, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error_body(request, str(exc.errors()), code="validation_error", status_code=422)
