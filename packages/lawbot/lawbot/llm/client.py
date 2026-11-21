from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from lawbot.crypto import decrypt_secret
from lawbot.db.models import LLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
_DEFAULT_LLM_STREAM_IDLE_SECONDS = 120.0
_DEFAULT_LLM_STREAM_MAX_SECONDS = 480.0
_DEFAULT_LLM_ANSWER_MAX_TOKENS = 800
_PROFILE_ANSWER_MAX_TOKENS = {
    "normal": 800,
    "compact": 500,
}


def _env_float_seconds(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    return max(1.0, value)


def get_llm_timeout_seconds() -> float:
    """Request/connect/first-byte timeout for LiteLLM completion (not whole-stream wall clock)."""
    return _env_float_seconds("LLM_TIMEOUT_SECONDS", _DEFAULT_LLM_TIMEOUT_SECONDS)


def get_llm_stream_idle_seconds() -> float:
    """Max silence between streamed chunks before truncating."""
    return _env_float_seconds("LLM_STREAM_IDLE_SECONDS", _DEFAULT_LLM_STREAM_IDLE_SECONDS)


def get_llm_stream_max_seconds() -> float:
    """Hard cap for an entire streamed completion."""
    return _env_float_seconds("LLM_STREAM_MAX_SECONDS", _DEFAULT_LLM_STREAM_MAX_SECONDS)


def get_llm_answer_max_tokens() -> int:
    """Max tokens for streamed legal answers only (not short classify JSON).

    Precedence: LLM_ANSWER_MAX_TOKENS > LLM_ANSWER_PROFILE (normal=800, compact=500) > 800.
    """
    raw = (os.environ.get("LLM_ANSWER_MAX_TOKENS") or "").strip()
    if raw:
        try:
            return max(64, int(raw))
        except ValueError:
            logger.warning(
                "Invalid LLM_ANSWER_MAX_TOKENS=%r; falling back to profile/default",
                raw,
            )
    profile = (os.environ.get("LLM_ANSWER_PROFILE") or "normal").strip().lower()
    if profile in _PROFILE_ANSWER_MAX_TOKENS:
        return _PROFILE_ANSWER_MAX_TOKENS[profile]
    if profile:
        logger.warning(
            "Invalid LLM_ANSWER_PROFILE=%r; using default %s",
            profile,
            _DEFAULT_LLM_ANSWER_MAX_TOKENS,
        )
    return _DEFAULT_LLM_ANSWER_MAX_TOKENS


class StreamTruncatedError(Exception):
    """Raised when a live stream is cut by idle or max timeout after some tokens may have been yielded."""

    def __init__(self, *, kind: str, chars_emitted: int, provider: str = "") -> None:
        self.kind = kind  # "idle" | "max"
        self.chars_emitted = int(chars_emitted)
        self.provider = provider or ""
        super().__init__(
            f"stream truncated kind={self.kind} chars={self.chars_emitted} provider={self.provider}"
        )


@dataclass
class ProviderCredentials:
    provider: LLMProvider
    api_key: str
    model: str
    base_url: str | None


def pick_enabled_provider(db: Session) -> LLMProvider | None:
    return db.scalar(
        select(LLMProvider)
        .where(LLMProvider.enabled.is_(True))
        .order_by(LLMProvider.priority.asc(), LLMProvider.created_at.asc())
        .limit(1)
    )


def resolve_provider_credentials(
    db: Session,
    *,
    encryption_key: str | None = None,
    jwt_secret: str | None = None,
) -> ProviderCredentials | None:
    row = pick_enabled_provider(db)
    if row is None:
        logger.info("No enabled llm_providers; using mock answer stream")
        return None
    api_key = decrypt_secret(
        row.api_key_encrypted,
        encryption_key=encryption_key,
        jwt_secret=jwt_secret,
    )
    return ProviderCredentials(
        provider=row,
        api_key=api_key,
        model=row.default_model,
        base_url=row.base_url,
    )


@dataclass
class EmbeddingCredentials:
    api_key: str
    api_base: str | None
    source: str  # env | llm_provider


def resolve_embedding_credentials(
    db: Session | None = None,
    *,
    embedding_api_key: str = "",
    embedding_api_base: str | None = None,
    encryption_key: str | None = None,
    jwt_secret: str | None = None,
) -> EmbeddingCredentials | None:
    """Prefer EMBEDDING_API_KEY; else reuse enabled Admin llm_providers key/base_url."""
    key = (embedding_api_key or "").strip()
    base = (embedding_api_base or None) or None
    if key:
        return EmbeddingCredentials(api_key=key, api_base=base, source="env")

    if db is None:
        return None
    creds = resolve_provider_credentials(
        db, encryption_key=encryption_key, jwt_secret=jwt_secret
    )
    if creds is None:
        return None
    return EmbeddingCredentials(
        api_key=creds.api_key,
        api_base=base or creds.base_url,
        source="llm_provider",
    )


def _litellm_model_name(provider: str, model: str) -> str:
    if "/" in model:
        return model
    mapping = {
        "openai": "openai",
        "deepseek": "deepseek",
        "dashscope": "dashscope",
        # OpenAI-compatible gateways (use recommended base_url)
        "zhipu": "openai",
        "moonshot": "openai",
        "ollama": "ollama",
        "openai_compatible": "openai",
    }
    prefix = mapping.get(provider, "openai")
    return f"{prefix}/{model}"


def _completion_messages(*, prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _completion_kwargs(
    *,
    prompt: str,
    credentials: ProviderCredentials,
    system: str | None,
    stream: bool = False,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    model = _litellm_model_name(credentials.provider.provider, credentials.model)
    kwargs: dict = {
        "model": model,
        "messages": _completion_messages(prompt=prompt, system=system),
        "api_key": credentials.api_key,
        "stream": stream,
        "timeout": timeout if timeout is not None else get_llm_timeout_seconds(),
    }
    if credentials.base_url:
        kwargs["api_base"] = credentials.base_url
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def complete_text(
    *,
    prompt: str,
    credentials: ProviderCredentials | None,
    system: str | None = None,
) -> str:
    """Call LiteLLM when credentials present; otherwise return mock text."""
    if credentials is None:
        return prompt  # caller supplies mock body; keep passthrough unused

    try:
        import litellm
    except ImportError:
        logger.warning("litellm not installed; falling back to mock")
        return ""

    try:
        resp = litellm.completion(
            **_completion_kwargs(prompt=prompt, credentials=credentials, system=system)
        )
        return resp.choices[0].message.content or ""
    except Exception:
        logger.exception(
            "LiteLLM completion failed/timed out for provider=%s; using mock",
            credentials.provider.name,
        )
        return ""


def complete_text_stream(
    *,
    prompt: str,
    credentials: ProviderCredentials | None,
    system: str | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Yield text deltas from LiteLLM stream=True.

    Empty iterator on failure / no credentials.
    Raises StreamTruncatedError on stream idle or max timeout (partial tokens already yielded).
    max_tokens defaults to LLM_ANSWER_MAX_TOKENS (answer streams only).
    """
    if credentials is None:
        return

    try:
        import litellm
    except ImportError:
        logger.warning("litellm not installed; falling back to mock stream")
        return

    req_timeout = get_llm_timeout_seconds()
    idle_seconds = get_llm_stream_idle_seconds()
    max_seconds = get_llm_stream_max_seconds()
    answer_max_tokens = (
        max_tokens if max_tokens is not None else get_llm_answer_max_tokens()
    )
    provider_name = credentials.provider.name
    started = time.monotonic()
    max_deadline = started + max_seconds
    idle_deadline = started + idle_seconds
    chars_emitted = 0

    try:
        stream = litellm.completion(
            **_completion_kwargs(
                prompt=prompt,
                credentials=credentials,
                system=system,
                stream=True,
                timeout=req_timeout,
                max_tokens=answer_max_tokens,
            )
        )
        for chunk in stream:
            now = time.monotonic()
            if now > max_deadline:
                logger.warning(
                    "LiteLLM stream truncated kind=max max_seconds=%.0f provider=%s chars_emitted=%s",
                    max_seconds,
                    provider_name,
                    chars_emitted,
                )
                raise StreamTruncatedError(
                    kind="max", chars_emitted=chars_emitted, provider=provider_name
                )
            if now > idle_deadline:
                logger.warning(
                    "LiteLLM stream truncated kind=idle idle_seconds=%.0f provider=%s chars_emitted=%s",
                    idle_seconds,
                    provider_name,
                    chars_emitted,
                )
                raise StreamTruncatedError(
                    kind="idle", chars_emitted=chars_emitted, provider=provider_name
                )
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                chars_emitted += len(text)
                idle_deadline = time.monotonic() + idle_seconds
                yield text
    except StreamTruncatedError:
        raise
    except Exception:
        logger.exception(
            "LiteLLM stream failed/timed out for provider=%s; falling back to mock",
            provider_name,
        )
        return


def humanize_connectivity_error(exc: BaseException) -> str:
    """Map LiteLLM / upstream errors to short Chinese messages for Admin UI."""
    raw = (str(exc) or "").strip() or type(exc).__name__
    text = f"{type(exc).__name__}: {raw}".lower()

    rules: list[tuple[tuple[str, ...], str]] = [
        (("litellm not installed",), "服务端未安装 litellm，无法测试连通"),
        (
            (
                "authentication",
                "unauthorized",
                "invalid api key",
                "incorrect api key",
                "invalid_api_key",
                "api key",
                "401",
            ),
            "API Key 无效或无权限，请检查密钥",
        ),
        (
            ("permission", "forbidden", "403"),
            "无访问权限，请检查账号或密钥权限",
        ),
        (
            ("rate limit", "ratelimit", "too many requests", "429"),
            "请求过于频繁，请稍后重试",
        ),
        (
            ("timeout", "timed out", "deadline exceeded"),
            "连接超时，请检查网络或 Base URL",
        ),
        (
            (
                "connection",
                "connecterror",
                "connect error",
                "name or service not known",
                "nodename nor servname",
                "getaddrinfo",
                "network is unreachable",
                "connection refused",
            ),
            "无法连接上游，请检查 Base URL 与网络",
        ),
        (
            ("ssl", "certificate", "cert verify"),
            "SSL/证书校验失败，请检查 Base URL 或证书配置",
        ),
        (
            (
                "model_not_found",
                "does not exist",
                "invalid model",
                "unknown model",
                "not a valid model",
            ),
            "模型不可用或不存在，请检查默认模型名称",
        ),
        (
            ("billing", "insufficient", "quota", "balance", "payment"),
            "上游额度不足或账户异常，请检查计费状态",
        ),
    ]
    for needles, zh in rules:
        if any(n in text for n in needles):
            return zh

    clipped = raw.replace("\n", " ")
    if len(clipped) > 120:
        clipped = clipped[:117] + "..."
    return f"连通失败：{clipped}"


def test_provider_connectivity(
    *,
    provider_kind: str,
    model: str,
    api_key: str,
    base_url: str | None,
) -> tuple[bool, str, str | None]:
    """Return (ok, message_zh, detail_raw). detail is set only on failure."""
    try:
        import litellm
    except ImportError:
        return False, "服务端未安装 litellm，无法测试连通", "litellm not installed"

    litellm_model = _litellm_model_name(provider_kind, model)
    kwargs: dict = {
        "model": litellm_model,
        "messages": [{"role": "user", "content": "ping"}],
        "api_key": api_key,
        "max_tokens": 5,
        "timeout": get_llm_timeout_seconds(),
    }
    if base_url:
        kwargs["api_base"] = base_url
    try:
        litellm.completion(**kwargs)
        return True, "连通正常", None
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        return False, humanize_connectivity_error(exc), detail
