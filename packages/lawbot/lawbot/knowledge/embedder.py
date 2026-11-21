from __future__ import annotations

import hashlib
import logging
import math
import struct
import time

logger = logging.getLogger(__name__)


def fake_embed(text: str, dim: int = 384) -> list[float]:
    """Deterministic pseudo-embedding for tests / offline import."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    seed = digest
    while len(values) < dim:
        seed = hashlib.sha256(seed).digest()
        for i in range(0, len(seed) - 3, 4):
            n = struct.unpack(">I", seed[i : i + 4])[0]
            values.append((n / 0xFFFFFFFF) * 2 - 1)
            if len(values) >= dim:
                break
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def normalize_embedding_model(model: str, api_base: str | None = None) -> str:
    """
    LiteLLM requires a provider prefix (e.g. openai/text-embedding-v3).
    OpenAI-compatible gateways (DashScope/MaaS compatible-mode) use the openai/ route.
    """
    m = (model or "").strip()
    if not m:
        return m
    if "/" in m:
        return m
    # Custom api_base almost always means OpenAI-compatible HTTP.
    if (api_base or "").strip():
        return f"openai/{m}"
    # Bare DashScope / Qwen embedding ids without base → still use openai-compatible
    # style so litellm does not raise "LLM Provider NOT provided".
    return f"openai/{m}"


def embed_texts(
    texts: list[str],
    *,
    model: str = "",
    api_key: str = "",
    api_base: str | None = None,
    dim: int = 384,
    mode: str = "auto",
) -> list[list[float]]:
    """
    mode:
      - fake: always hash embed
      - litellm: call litellm.embedding
      - auto: litellm if model+api_key else fake
    """
    use_fake = mode == "fake" or (mode == "auto" and (not model or not api_key))
    if use_fake:
        if mode == "auto":
            logger.info("Embedding with fake vectors (no EMBEDDING_MODEL/API_KEY)")
        return [fake_embed(t, dim=dim) for t in texts]

    try:
        import litellm
    except ImportError:
        logger.warning("litellm missing; fake embeddings")
        return [fake_embed(t, dim=dim) for t in texts]

    litellm_model = normalize_embedding_model(model, api_base)
    # Explicit provider avoids LiteLLM "Unmapped LLM provider" / "Provider NOT provided".
    provider = litellm_model.split("/", 1)[0] if "/" in litellm_model else "openai"
    # DashScope compatible embeddings reject batches larger than 10.
    batch_limit = 10
    out: list[list[float]] = []
    t0 = time.monotonic()
    try:
        for i in range(0, len(texts), batch_limit):
            chunk = texts[i : i + batch_limit]
            kwargs: dict = {
                "model": litellm_model,
                "input": chunk,
                "api_key": api_key,
                "custom_llm_provider": provider,
            }
            if api_base:
                kwargs["api_base"] = api_base
            resp = litellm.embedding(**kwargs)
            out.extend(item["embedding"] for item in resp.data)
        logger.info(
            "agent_timing embed_ms=%s n=%s model=%s",
            int((time.monotonic() - t0) * 1000),
            len(texts),
            litellm_model,
        )
        return out
    except Exception:
        if mode == "litellm":
            logger.exception(
                "litellm.embedding failed; not falling back to fake model=%s litellm_model=%s",
                model,
                litellm_model,
            )
            raise
        logger.exception("litellm.embedding failed; fake embeddings")
        return [fake_embed(t, dim=dim) for t in texts]
