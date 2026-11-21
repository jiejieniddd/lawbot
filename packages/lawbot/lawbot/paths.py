"""Repo-root aware path helpers (cwd-independent relative paths)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DEFAULT_RAG_MEMORY_REL = "data/rag_memory"


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Locate monorepo root (has root pyproject.toml and packages/lawbot/)."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages" / "lawbot").is_dir():
            return candidate
    # packages/lawbot/lawbot/paths.py → parents[3] == repo root in normal layout
    return here.parents[3]


def resolve_rag_memory_dir(raw: str | Path | None = None) -> Path:
    """Resolve RAG memory dir relative to repo root (absolute paths unchanged).

    Empty / None → ``data/rag_memory`` under repo root.
    Absolute path → expanduser + resolve as-is (Docker / local override).
    Relative path → ``repo_root() / raw``, independent of process cwd.
    """
    text = (str(raw) if raw is not None else "").strip() or DEFAULT_RAG_MEMORY_REL
    path = Path(text).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (repo_root() / path).resolve()
