"""Admin embedding settings: load/save/test. Vector embedding — not chat LLM / tokenizer."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings
from lawbot.db.models import EmbeddingSettings
from lawbot.knowledge.embedder import embed_texts
from lawbot.knowledge.embedding_settings import (
    MODE_VALUES,
    REINDEX_HINT,
    SINGLETON_ID,
    EnvEmbeddingDefaults,
    ResolvedEmbedding,
    encrypt_embedding_api_key,
    require_litellm_ready,
    resolve_embedding_config,
)


class EmbeddingSettingsUpdate(BaseModel):
    mode: str = "auto"
    embedding_model: str = Field(default="", max_length=255)
    api_key: str = Field(default="", max_length=512)
    api_base: str = Field(default="", max_length=512)
    embedding_dim: int = Field(default=384, ge=8, le=8192)
    reuse_llm_provider: bool = False


class EmbeddingTestBody(BaseModel):
    """Optional overrides for connectivity test (empty fields use saved/env config)."""

    mode: str | None = None
    embedding_model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    embedding_dim: int | None = Field(default=None, ge=8, le=8192)
    reuse_llm_provider: bool | None = None


def env_defaults_from_settings(settings: Settings) -> EnvEmbeddingDefaults:
    return EnvEmbeddingDefaults(
        mode=settings.embedding_mode or "auto",
        embedding_model=settings.embedding_model or "",
        api_key=settings.embedding_api_key or "",
        api_base=settings.embedding_api_base,
        embedding_dim=int(settings.embedding_dim or 384),
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )


def get_embedding_public(db: Session, settings: Settings) -> dict:
    resolved = resolve_embedding_config(db, env_defaults_from_settings(settings))
    return resolved.public_dict()


def save_embedding_config(
    db: Session,
    settings: Settings,
    body: EmbeddingSettingsUpdate,
) -> dict:
    mode = (body.mode or "auto").strip().lower()
    if mode not in MODE_VALUES:
        raise ValueError("Embedding mode 无效，可选 fake / litellm / auto")
    model = (body.embedding_model or "").strip()
    if mode == "litellm" and not model:
        raise ValueError("mode=litellm 时必须填写 embedding_model（向量模型名，不是聊天模型）")

    env = env_defaults_from_settings(settings)
    row = db.get(EmbeddingSettings, SINGLETON_ID)
    if row is None:
        row = EmbeddingSettings(id=SINGLETON_ID)
        stored_key = ""
        db.add(row)
    else:
        stored_key = row.api_key_encrypted or ""

    if body.api_key.strip():
        stored_key = encrypt_embedding_api_key(body.api_key.strip(), env)

    if mode == "litellm":
        has_stored = bool(stored_key)
        if not body.reuse_llm_provider and not has_stored and not (env.api_key or "").strip():
            raise ValueError("请填写 Embedding API Key，或开启「复用聊天供应商密钥」")

    row.mode = mode
    row.embedding_model = model
    row.api_key_encrypted = stored_key
    row.api_base = (body.api_base or "").strip()
    row.embedding_dim = int(body.embedding_dim)
    row.reuse_llm_provider = bool(body.reuse_llm_provider)
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        from app.retriever_dep import clear_retriever_cache

        clear_retriever_cache()
    except Exception:
        pass

    out = resolve_embedding_config(db, env).public_dict()
    out["detail"] = f"已保存。{REINDEX_HINT}"
    return out


def _apply_test_overrides(
    db: Session,
    settings: Settings,
    body: EmbeddingTestBody,
) -> ResolvedEmbedding:
    env = env_defaults_from_settings(settings)
    base = resolve_embedding_config(db, env)

    mode = base.mode
    if body.mode is not None and body.mode.strip():
        mode = body.mode.strip().lower()  # type: ignore[assignment]
        if mode not in MODE_VALUES:
            raise ValueError("Embedding mode 无效，可选 fake / litellm / auto")

    model = base.embedding_model
    if body.embedding_model is not None:
        model = body.embedding_model.strip()

    dim = base.embedding_dim
    if body.embedding_dim is not None:
        dim = int(body.embedding_dim)

    reuse = base.reuse_llm_provider
    if body.reuse_llm_provider is not None:
        reuse = bool(body.reuse_llm_provider)

    api_key = base.api_key
    api_base = base.api_base
    source = base.source
    if body.api_key is not None and body.api_key.strip():
        api_key = body.api_key.strip()
        source = "db"
    if body.api_base is not None:
        api_base = body.api_base.strip() or None

    if reuse and not (body.api_key and body.api_key.strip()):
        # Re-resolve with reuse flag via temporary row-like path
        from lawbot.llm.client import resolve_provider_credentials

        creds = resolve_provider_credentials(
            db,
            encryption_key=env.encryption_key,
            jwt_secret=env.jwt_secret,
        )
        if creds is not None:
            api_key = creds.api_key
            api_base = api_base or creds.base_url
            source = "llm_provider"

    from lawbot.knowledge.embedding_settings import _effective_mode, _norm_mode

    mode_n = _norm_mode(mode)
    return ResolvedEmbedding(
        mode=mode_n,
        embedding_model=model,
        api_key=api_key,
        api_base=api_base,
        embedding_dim=dim,
        reuse_llm_provider=reuse,
        api_key_configured=bool(api_key),
        source=source,  # type: ignore[arg-type]
        effective_mode=_effective_mode(mode=mode_n, model=model, api_key=api_key),
        api_key_unreadable=base.api_key_unreadable,
    )


def format_embedding_call_error(exc: BaseException, *, model: str = "") -> str:
    """Map provider/LiteLLM exceptions to short Chinese, actionable hints."""
    raw = str(exc).strip() or exc.__class__.__name__
    low = raw.lower()
    model_hint = (model or "").strip()

    def _tail(extra: str = "") -> str:
        # Keep a short vendor snippet for support/debug; strip secrets-ish noise.
        snippet = raw.replace("\n", " ")
        for token in ("api_key", "Authorization", "Bearer "):
            if token.lower() in snippet.lower():
                snippet = snippet[:80]
                break
        snippet = snippet[:160]
        return f"{extra}（详情：{snippet}）" if extra else f"Embedding 调用失败：{snippet}"

    if any(
        k in low
        for k in (
            "invalid api key",
            "incorrect api key",
            "authentication",
            "unauthorized",
            "401",
            "invalid_api_key",
            "access key",
            "api key is invalid",
        )
    ):
        return _tail("API Key 无效或未授权，请检查 Embedding Key，或关闭「复用聊天供应商」后单独填写")

    if any(k in low for k in ("403", "permission", "forbidden", "access denied")):
        return _tail("无调用权限，请确认该 Key 已开通向量（Embedding）能力")

    if (
        "llm provider not provided" in low
        or "pass in the llm provider" in low
        or "unmapped llm provider" in low
        or "custom_llm_provider=none" in low
    ):
        return _tail(
            "LiteLLM 无法路由该 Embedding 模型。请保存后重试（系统会自动加 openai/ 前缀）；"
            "也可手动把模型名写成 openai/qwen3.7-text-embedding-flash，并确认 API Base 为 compatible-mode"
        )

    if any(
        k in low
        for k in (
            "model_not_found",
            "does not exist",
            "not found",
            "unknown model",
            "invalid model",
            "unsupported model",
            "no such model",
            "is not a valid model",
        )
    ):
        suggest = "请改用专用向量模型（如 text-embedding-v3 / text-embedding-v4），不要填聊天模型名"
        if model_hint:
            return _tail(f"模型「{model_hint}」不可用或不是 Embedding 模型。{suggest}")
        return _tail(f"模型不可用或不是 Embedding 模型。{suggest}")

    if any(k in low for k in ("429", "rate limit", "too many requests", "quota", "限流", "额度")):
        return _tail("调用过于频繁或额度不足，请稍后重试或检查账单/限流")

    if any(k in low for k in ("timeout", "timed out", "deadline", "超时")):
        return _tail("Embedding 请求超时，请检查网络或稍后重试")

    if any(
        k in low
        for k in (
            "connection",
            "connect",
            "name or service",
            "nodename",
            "getaddrinfo",
            "ssl",
            "certificate",
            "refused",
            "unreachable",
        )
    ):
        return _tail("无法连接 Embedding 服务，请检查 API Base 与网络")

    if any(k in low for k in ("dimension", "dimensions", "dim mismatch", "vector size", "embedding size")):
        return _tail("向量维度与模型不匹配，请用「测试连通」返回的实际 dim 更新配置后重灌")

    if any(k in low for k in ("bad request", "400", "invalid_request")):
        return _tail(
            "请求参数被拒绝。请确认模型名为向量模型、API Base 正确"
            + (f"（当前模型：{model_hint}）" if model_hint else "")
        )

    return _tail()


def test_embedding_connectivity(
    db: Session,
    settings: Settings,
    body: EmbeddingTestBody | None = None,
) -> dict:
    body = body or EmbeddingTestBody()
    try:
        resolved = _apply_test_overrides(db, settings, body)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}

    if resolved.mode == "fake" or resolved.effective_mode == "fake":
        if resolved.mode == "litellm":
            err = require_litellm_ready(resolved)
            if err:
                return {"ok": False, "detail": err}
        return {
            "ok": True,
            "dim": resolved.embedding_dim,
            "detail": f"当前为本地假向量（fake），维度 {resolved.embedding_dim}",
        }

    err = require_litellm_ready(
        ResolvedEmbedding(
            mode="litellm",
            embedding_model=resolved.embedding_model,
            api_key=resolved.api_key,
            api_base=resolved.api_base,
            embedding_dim=resolved.embedding_dim,
            reuse_llm_provider=resolved.reuse_llm_provider,
            api_key_configured=resolved.api_key_configured,
            source=resolved.source,
            effective_mode="litellm",
        )
    )
    if err:
        return {"ok": False, "detail": err}

    try:
        vectors = embed_texts(
            ["CareerBot embedding connectivity test"],
            model=resolved.embedding_model,
            api_key=resolved.api_key,
            api_base=resolved.api_base,
            dim=resolved.embedding_dim,
            mode="litellm",
        )
    except Exception as exc:
        return {
            "ok": False,
            "detail": format_embedding_call_error(exc, model=resolved.embedding_model),
        }

    if not vectors or not vectors[0]:
        return {"ok": False, "detail": "Embedding 返回空向量，请检查模型是否支持 embeddings 接口"}
    actual_dim = len(vectors[0])
    hint = ""
    if actual_dim != resolved.embedding_dim:
        hint = (
            f"（与配置 embedding_dim={resolved.embedding_dim} 不一致，"
            f"请改为 {actual_dim} 后重新导入知识库）"
        )
    return {
        "ok": True,
        "dim": actual_dim,
        "detail": f"连通成功，实际向量维度 {actual_dim}{hint}",
    }
