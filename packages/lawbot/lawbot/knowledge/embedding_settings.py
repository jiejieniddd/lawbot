"""Singleton embedding (vector) settings resolve — not chat LLM, not tokenizer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from lawbot.crypto import decrypt_secret, encrypt_secret
from lawbot.db.models import EmbeddingSettings
from lawbot.llm.client import resolve_provider_credentials

SINGLETON_ID = 1
MODE_VALUES = frozenset({"fake", "litellm", "auto"})
REINDEX_HINT = "修改 mode / model / dim 后必须重新导入知识库，勿与旧索引混用。"

Source = Literal["db", "env", "llm_provider", "none"]
Mode = Literal["fake", "litellm", "auto"]


@dataclass
class ResolvedEmbedding:
    mode: Mode
    embedding_model: str
    api_key: str
    api_base: str | None
    embedding_dim: int
    reuse_llm_provider: bool
    api_key_configured: bool
    source: Source
    effective_mode: Mode
    api_key_unreadable: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "embedding_model": self.embedding_model,
            "api_base": self.api_base or "",
            "embedding_dim": self.embedding_dim,
            "reuse_llm_provider": self.reuse_llm_provider,
            "api_key_configured": self.api_key_configured,
            "effective_mode": self.effective_mode,
            "source": self.source,
            "reindex_required_hint": REINDEX_HINT,
        }


@dataclass
class EnvEmbeddingDefaults:
    mode: str = "auto"
    embedding_model: str = ""
    api_key: str = ""
    api_base: str | None = None
    embedding_dim: int = 384
    encryption_key: str | None = None
    jwt_secret: str | None = None


def _norm_mode(value: str | None) -> Mode:
    raw = (value or "auto").strip().lower()
    if raw in MODE_VALUES:
        return raw  # type: ignore[return-value]
    return "auto"


def _effective_mode(*, mode: Mode, model: str, api_key: str) -> Mode:
    if mode == "fake":
        return "fake"
    if mode == "litellm":
        return "litellm"
    # auto
    if (model or "").strip() and (api_key or "").strip():
        return "litellm"
    return "fake"


def _crypto_kwargs(env: EnvEmbeddingDefaults) -> dict[str, str | None]:
    return {
        "encryption_key": env.encryption_key,
        "jwt_secret": env.jwt_secret,
    }


def encrypt_embedding_api_key(plaintext: str, env: EnvEmbeddingDefaults) -> str:
    if not plaintext:
        return ""
    return encrypt_secret(plaintext, **_crypto_kwargs(env))


def decrypt_embedding_api_key(ciphertext: str, env: EnvEmbeddingDefaults) -> str:
    if not ciphertext:
        return ""
    return decrypt_secret(ciphertext, **_crypto_kwargs(env))


def resolve_embedding_config(
    db: Session | None,
    env: EnvEmbeddingDefaults,
    *,
    mode_override: str | None = None,
) -> ResolvedEmbedding:
    """
    Priority for key/base:
      1. DB key (when row exists and not reuse_llm_provider)
      2. reuse_llm_provider → enabled chat LLM provider key/base
      3. env EMBEDDING_API_KEY / BASE
    mode/model/dim: DB row if present else env; mode_override wins when set.
    """
    row: EmbeddingSettings | None = None
    if db is not None:
        row = db.get(EmbeddingSettings, SINGLETON_ID)

    if row is None:
        mode = _norm_mode(mode_override if mode_override is not None else env.mode)
        model = (env.embedding_model or "").strip()
        key = (env.api_key or "").strip()
        base = (env.api_base or None) or None
        dim = int(env.embedding_dim or 384)
        reuse = False
        source: Source = "env" if key else "none"
        # Optional: still allow reuse-style fallback from LLM when only env mode/model set
        if not key and db is not None:
            creds = resolve_provider_credentials(
                db,
                encryption_key=env.encryption_key,
                jwt_secret=env.jwt_secret,
            )
            if creds is not None:
                key = creds.api_key
                base = base or creds.base_url
                source = "llm_provider"
        return ResolvedEmbedding(
            mode=mode,
            embedding_model=model,
            api_key=key,
            api_base=base,
            embedding_dim=max(1, dim),
            reuse_llm_provider=reuse,
            api_key_configured=bool(key) or bool((env.api_key or "").strip()),
            source=source,
            effective_mode=_effective_mode(mode=mode, model=model, api_key=key),
        )

    mode = _norm_mode(mode_override if mode_override is not None else row.mode)
    model = (row.embedding_model or "").strip() or (env.embedding_model or "").strip()
    dim = int(row.embedding_dim or env.embedding_dim or 384)
    reuse = bool(row.reuse_llm_provider)
    ciphertext = row.api_key_encrypted or ""
    db_key = ""
    unreadable = False
    if ciphertext:
        try:
            db_key = decrypt_embedding_api_key(ciphertext, env)
        except ValueError:
            unreadable = True

    row_base = (row.api_base or "").strip() or None
    env_key = (env.api_key or "").strip()
    env_base = (env.api_base or None) or None

    key = ""
    base: str | None = row_base or env_base
    source: Source = "db"

    if reuse:
        creds = None
        if db is not None:
            creds = resolve_provider_credentials(
                db,
                encryption_key=env.encryption_key,
                jwt_secret=env.jwt_secret,
            )
        if creds is not None:
            key = creds.api_key
            base = row_base or creds.base_url or env_base
            source = "llm_provider"
        elif db_key:
            key = db_key
            source = "db"
        elif env_key:
            key = env_key
            base = row_base or env_base
            source = "env"
        else:
            source = "none"
    elif db_key:
        key = db_key
        source = "db"
    elif env_key:
        key = env_key
        base = row_base or env_base
        source = "env"
    else:
        source = "none"

    return ResolvedEmbedding(
        mode=mode,
        embedding_model=model,
        api_key=key,
        api_base=base,
        embedding_dim=max(1, dim),
        reuse_llm_provider=reuse,
        api_key_configured=bool(ciphertext) or bool(env_key) or (source == "llm_provider" and bool(key)),
        source=source,
        effective_mode=_effective_mode(mode=mode, model=model, api_key=key),
        api_key_unreadable=unreadable,
    )


def require_litellm_ready(resolved: ResolvedEmbedding) -> str | None:
    """Return Chinese error if litellm path is incomplete; else None."""
    if resolved.mode != "litellm":
        return None
    if not (resolved.embedding_model or "").strip():
        return "请填写 embedding_model（向量模型名，不是聊天模型）"
    if not (resolved.api_key or "").strip():
        if resolved.api_key_unreadable:
            return "Embedding API Key 无法解密，请重新填写"
        return "请配置 Embedding API Key，或开启「复用聊天供应商密钥」"
    return None
