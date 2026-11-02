from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.deps import require_admin
from lawbot.db.models import User

router = APIRouter(prefix="/settings", tags=["admin-settings"])


@router.get("")
def get_settings_redacted(
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_admin),
) -> dict:
    def mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "****"
        return value[:2] + "****" + value[-2:]

    return {
        "app_env": settings.app_env,
        "database_url": mask(settings.database_url),
        "redis_url": mask(settings.redis_url),
        "llm_source": "db.llm_providers (preferred); env LITELLM_* is legacy optional only",
        "litellm_model": settings.litellm_model or "(unused if providers configured)",
        "litellm_api_key": mask(settings.litellm_api_key),
        "encryption_key_configured": bool(settings.encryption_key),
        "cors_origins": settings.cors_origin_list,
        "access_token_expire_minutes": settings.access_token_expire_minutes,
        "refresh_token_expire_days": settings.refresh_token_expire_days,
    }
