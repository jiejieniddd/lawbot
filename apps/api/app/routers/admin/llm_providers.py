from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import get_db, require_admin
from lawbot.crypto import decrypt_secret, encrypt_secret, mask_api_key
from lawbot.db.models import LLMProvider, User
from lawbot.domain.schemas import LLMProviderCreate, LLMProviderOut, LLMProviderPatch
from lawbot.llm.catalog import get_llm_provider_catalog
from lawbot.llm.client import test_provider_connectivity

router = APIRouter(prefix="/llm-providers", tags=["admin-llm-providers"])


@router.get("/catalog")
def provider_catalog(_: User = Depends(require_admin)) -> dict:
    """Read-only model/provider catalog for Admin UI presets."""
    return get_llm_provider_catalog()


def _to_out(row: LLMProvider, settings: Settings) -> LLMProviderOut:
    try:
        plain = decrypt_secret(
            row.api_key_encrypted,
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.secret_key,
        )
        masked = mask_api_key(plain)
    except Exception:
        masked = "****"
    return LLMProviderOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        base_url=row.base_url,
        default_model=row.default_model,
        priority=row.priority,
        enabled=row.enabled,
        api_key_masked=masked,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[LLMProviderOut])
def list_providers(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> list[LLMProviderOut]:
    rows = db.scalars(select(LLMProvider).order_by(LLMProvider.priority.asc())).all()
    return [_to_out(r, settings) for r in rows]


@router.post("", response_model=LLMProviderOut, status_code=status.HTTP_201_CREATED)
def create_provider(
    body: LLMProviderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> LLMProviderOut:
    row = LLMProvider(
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        api_key_encrypted=encrypt_secret(
            body.api_key,
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.secret_key,
        ),
        default_model=body.default_model,
        priority=body.priority,
        enabled=body.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row, settings)


@router.patch("/{provider_id}", response_model=LLMProviderOut)
def patch_provider(
    provider_id: UUID,
    body: LLMProviderPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> LLMProviderOut:
    row = db.get(LLMProvider, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    data = body.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    for k, v in data.items():
        setattr(row, k, v.value if hasattr(v, "value") else v)
    if api_key:
        row.api_key_encrypted = encrypt_secret(
            api_key,
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.secret_key,
        )
    db.commit()
    db.refresh(row)
    return _to_out(row, settings)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    row = db.get(LLMProvider, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    db.delete(row)
    db.commit()


@router.post("/{provider_id}/test")
def test_provider(
    provider_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = db.get(LLMProvider, provider_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")
    try:
        api_key = decrypt_secret(
            row.api_key_encrypted,
            encryption_key=settings.encryption_key or None,
            jwt_secret=settings.secret_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Cannot decrypt api key") from exc
    ok, message = test_provider_connectivity(
        provider_kind=row.provider,
        model=row.default_model,
        api_key=api_key,
        base_url=row.base_url,
    )
    return {"ok": ok, "message": message}
