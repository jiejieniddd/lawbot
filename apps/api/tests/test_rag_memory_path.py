from __future__ import annotations

from pathlib import Path

from lawbot.paths import repo_root, resolve_rag_memory_dir


def test_resolve_relative_memory_dir_independent_of_cwd(tmp_path, monkeypatch):
    root = repo_root()
    expected = (root / "data" / "rag_memory").resolve()

    api_cwd = root / "apps" / "api"
    assert api_cwd.is_dir()
    monkeypatch.chdir(api_cwd)
    assert Path.cwd().resolve() == api_cwd.resolve()

    resolved = resolve_rag_memory_dir("data/rag_memory")
    assert resolved == expected
    # Must not resolve under apps/api/...
    assert resolved != (api_cwd / "data" / "rag_memory").resolve()


def test_resolve_absolute_memory_dir_unchanged(tmp_path):
    absolute = (tmp_path / "custom_rag").resolve()
    absolute.mkdir()
    resolved = resolve_rag_memory_dir(str(absolute))
    assert resolved == absolute


def test_resolve_empty_uses_default_under_repo():
    resolved = resolve_rag_memory_dir("")
    assert resolved == (repo_root() / "data" / "rag_memory").resolve()


def test_settings_resolved_rag_memory_dir(monkeypatch):
    monkeypatch.setenv("RAG_MEMORY_DIR", "data/rag_memory")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        s = get_settings()
        assert Path(s.resolved_rag_memory_dir) == (repo_root() / "data" / "rag_memory").resolve()
    finally:
        get_settings.cache_clear()
