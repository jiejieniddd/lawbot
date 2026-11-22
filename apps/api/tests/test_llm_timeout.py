from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from lawbot.llm import client as llm_client
from lawbot.llm.client import (
    ProviderCredentials,
    StreamTruncatedError,
    complete_text,
    complete_text_stream,
    get_llm_answer_max_tokens,
    get_llm_stream_idle_seconds,
    get_llm_stream_max_seconds,
    get_llm_timeout_seconds,
)


def _creds() -> ProviderCredentials:
    return ProviderCredentials(
        provider=SimpleNamespace(provider="openai", name="demo"),
        api_key="sk-test",
        model="gpt-test",
        base_url=None,
    )


def _chunk(text: str | None, *, finish_reason: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ]
    )


def test_get_llm_timeout_seconds_default(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    assert get_llm_timeout_seconds() == 60.0


def test_get_llm_timeout_seconds_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    assert get_llm_timeout_seconds() == 12.5


def test_get_llm_stream_idle_max_defaults(monkeypatch):
    monkeypatch.delenv("LLM_STREAM_IDLE_SECONDS", raising=False)
    monkeypatch.delenv("LLM_STREAM_MAX_SECONDS", raising=False)
    assert get_llm_stream_idle_seconds() == 120.0
    assert get_llm_stream_max_seconds() == 480.0


def test_get_llm_stream_idle_max_from_env(monkeypatch):
    monkeypatch.setenv("LLM_STREAM_IDLE_SECONDS", "2.5")
    monkeypatch.setenv("LLM_STREAM_MAX_SECONDS", "9")
    assert get_llm_stream_idle_seconds() == 2.5
    assert get_llm_stream_max_seconds() == 9.0


def test_complete_text_timeout_returns_empty(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "5")

    def boom_completion(**kwargs):
        assert kwargs.get("timeout") == 5.0
        raise TimeoutError("Request timed out")

    monkeypatch.setattr("litellm.completion", boom_completion)
    assert complete_text(prompt="hi", credentials=_creds()) == ""


def test_complete_text_stream_timeout_empty(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "3")

    def boom_completion(**kwargs):
        assert kwargs.get("timeout") == 3.0
        raise TimeoutError("timed out")

    monkeypatch.setattr("litellm.completion", boom_completion)
    assert list(complete_text_stream(prompt="hi", credentials=_creds())) == []


def test_complete_text_stream_idle_truncates(monkeypatch):
    # Floor is 1.0s; advance monotonic past idle between chunks.
    monkeypatch.setenv("LLM_STREAM_IDLE_SECONDS", "1")
    monkeypatch.setenv("LLM_STREAM_MAX_SECONDS", "30")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")

    clock = {"t": 1000.0}

    def fake_monotonic():
        return clock["t"]

    def gappy_stream(**_kwargs):
        yield _chunk("hello")
        clock["t"] += 1.5  # idle gap before next chunk
        yield _chunk("world")

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr("litellm.completion", gappy_stream)

    parts: list[str] = []
    with pytest.raises(StreamTruncatedError) as ei:
        for piece in complete_text_stream(prompt="hi", credentials=_creds()):
            parts.append(piece)
    assert "".join(parts) == "hello"
    assert ei.value.kind == "idle"
    assert ei.value.chars_emitted == len("hello")


def test_complete_text_stream_max_truncates(monkeypatch):
    monkeypatch.setenv("LLM_STREAM_IDLE_SECONDS", "30")
    monkeypatch.setenv("LLM_STREAM_MAX_SECONDS", "1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")

    clock = {"t": 1000.0}

    def fake_monotonic():
        return clock["t"]

    def long_stream(**_kwargs):
        yield _chunk("a")
        clock["t"] += 1.5  # past max hard cap
        yield _chunk("b")

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr("litellm.completion", long_stream)

    parts: list[str] = []
    with pytest.raises(StreamTruncatedError) as ei:
        for piece in complete_text_stream(prompt="hi", credentials=_creds()):
            parts.append(piece)
    assert "".join(parts) == "a"
    assert ei.value.kind == "max"
    assert ei.value.chars_emitted == 1


def test_complete_text_stream_normal_finish_no_truncate(monkeypatch):
    monkeypatch.setenv("LLM_STREAM_IDLE_SECONDS", "5")
    monkeypatch.setenv("LLM_STREAM_MAX_SECONDS", "30")

    def quick_stream(**_kwargs):
        yield _chunk("ok")
        yield _chunk("-done", finish_reason="stop")

    monkeypatch.setattr("litellm.completion", quick_stream)
    assert list(complete_text_stream(prompt="hi", credentials=_creds())) == ["ok", "-done"]


def test_get_llm_answer_max_tokens_default(monkeypatch):
    monkeypatch.delenv("LLM_ANSWER_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LLM_ANSWER_PROFILE", raising=False)
    assert get_llm_answer_max_tokens() == 1600


def test_get_llm_answer_max_tokens_profile_and_explicit(monkeypatch):
    monkeypatch.delenv("LLM_ANSWER_MAX_TOKENS", raising=False)
    monkeypatch.setenv("LLM_ANSWER_PROFILE", "compact")
    assert get_llm_answer_max_tokens() == 800
    monkeypatch.setenv("LLM_ANSWER_MAX_TOKENS", "1200")
    assert get_llm_answer_max_tokens() == 1200


def test_complete_text_stream_length_finish_raises(monkeypatch):
    monkeypatch.setenv("LLM_STREAM_IDLE_SECONDS", "30")
    monkeypatch.setenv("LLM_STREAM_MAX_SECONDS", "60")

    def length_stream(**_kwargs):
        yield _chunk("partial")
        yield _chunk(None, finish_reason="length")

    monkeypatch.setattr("litellm.completion", length_stream)

    parts: list[str] = []
    with pytest.raises(StreamTruncatedError) as ei:
        for piece in complete_text_stream(prompt="hi", credentials=_creds()):
            parts.append(piece)
    assert "".join(parts) == "partial"
    assert ei.value.kind == "length"
    assert ei.value.chars_emitted == len("partial")


def test_connectivity_passes_timeout(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "7")
    seen: dict = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))])

    monkeypatch.setattr("litellm.completion", fake_completion)
    ok, msg, detail = llm_client.test_provider_connectivity(
        provider_kind="openai",
        model="gpt-test",
        api_key="sk-test",
        base_url=None,
    )
    assert ok is True
    assert msg == "连通正常"
    assert detail is None
    assert seen.get("timeout") == 7.0
