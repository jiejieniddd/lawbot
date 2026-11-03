from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from lawbot.crypto import decrypt_secret
from lawbot.db.models import LLMProvider

logger = logging.getLogger(__name__)


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
) -> dict:
    model = _litellm_model_name(credentials.provider.provider, credentials.model)
    kwargs: dict = {
        "model": model,
        "messages": _completion_messages(prompt=prompt, system=system),
        "api_key": credentials.api_key,
        "stream": stream,
    }
    if credentials.base_url:
        kwargs["api_base"] = credentials.base_url
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
        resp = litellm.completion(**_completion_kwargs(prompt=prompt, credentials=credentials, system=system))
        return resp.choices[0].message.content or ""
    except Exception:
        logger.exception("LiteLLM completion failed for provider=%s; using mock", credentials.provider.name)
        return ""


def complete_text_stream(
    *,
    prompt: str,
    credentials: ProviderCredentials | None,
    system: str | None = None,
) -> Iterator[str]:
    """Yield text deltas from LiteLLM stream=True. Empty iterator on failure / no credentials."""
    if credentials is None:
        return

    try:
        import litellm
    except ImportError:
        logger.warning("litellm not installed; falling back to mock stream")
        return

    try:
        stream = litellm.completion(
            **_completion_kwargs(
                prompt=prompt,
                credentials=credentials,
                system=system,
                stream=True,
            )
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
    except Exception:
        logger.exception(
            "LiteLLM stream failed for provider=%s; falling back to mock",
            credentials.provider.name,
        )
        return


def test_provider_connectivity(
    *,
    provider_kind: str,
    model: str,
    api_key: str,
    base_url: str | None,
) -> tuple[bool, str]:
    try:
        import litellm
    except ImportError:
        return False, "litellm not installed"

    litellm_model = _litellm_model_name(provider_kind, model)
    kwargs: dict = {
        "model": litellm_model,
        "messages": [{"role": "user", "content": "ping"}],
        "api_key": api_key,
        "max_tokens": 5,
    }
    if base_url:
        kwargs["api_base"] = base_url
    try:
        litellm.completion(**kwargs)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
