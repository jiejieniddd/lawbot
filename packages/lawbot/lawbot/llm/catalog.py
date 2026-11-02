from __future__ import annotations

from typing import Any

CUSTOM_MODEL_VALUE = "__custom__"


def _models(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    items = [{"value": value, "label": label} for value, label in pairs]
    items.append({"value": CUSTOM_MODEL_VALUE, "label": "自定义"})
    return items


LLM_PROVIDER_CATALOG: list[dict[str, Any]] = [
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "recommended_base_url": "https://api.deepseek.com",
        "models": _models(
            ("deepseek-chat", "deepseek-chat"),
            ("deepseek-reasoner", "deepseek-reasoner"),
        ),
    },
    {
        "value": "openai",
        "label": "OpenAI",
        "recommended_base_url": "https://api.openai.com/v1",
        "models": _models(
            ("gpt-4o", "gpt-4o"),
            ("gpt-4o-mini", "gpt-4o-mini"),
            ("gpt-4.1", "gpt-4.1"),
        ),
    },
    {
        "value": "dashscope",
        "label": "通义千问 (DashScope)",
        "recommended_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": _models(
            ("qwen-plus", "qwen-plus"),
            ("qwen-turbo", "qwen-turbo"),
            ("qwen-max", "qwen-max"),
        ),
    },
    {
        "value": "zhipu",
        "label": "智谱 (Zhipu)",
        "recommended_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": _models(
            ("glm-4", "glm-4"),
            ("glm-4-flash", "glm-4-flash"),
        ),
    },
    {
        "value": "moonshot",
        "label": "Moonshot (Kimi)",
        "recommended_base_url": "https://api.moonshot.cn/v1",
        "models": _models(
            ("moonshot-v1-8k", "moonshot-v1-8k"),
            ("moonshot-v1-32k", "moonshot-v1-32k"),
        ),
    },
    {
        "value": "openai_compatible",
        "label": "OpenAI Compatible",
        "recommended_base_url": None,
        "models": _models(
            ("gpt-4o-mini", "gpt-4o-mini"),
            ("deepseek-chat", "deepseek-chat"),
        ),
    },
    {
        "value": "ollama",
        "label": "Ollama",
        "recommended_base_url": "http://127.0.0.1:11434",
        "models": _models(
            ("llama3.2", "llama3.2"),
            ("qwen2.5", "qwen2.5"),
        ),
    },
]


def get_llm_provider_catalog() -> dict[str, Any]:
    return {"providers": LLM_PROVIDER_CATALOG}
