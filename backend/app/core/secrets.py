"""Resolve credential references.

Registries (LLM models, graph databases) store only the *name* of an environment variable. Its value
comes from the process environment first, then from the same ``.env`` files the application settings
read, so a credential defined in ``.env`` works without being exported in the shell. Values are
never logged, stored or returned by the API.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

from app.core.config import BACKEND_DIR, REPO_ROOT

# Highest priority first, matching how the application settings layer these files.
ENV_FILES: tuple[Path, ...] = (BACKEND_DIR / ".env", REPO_ROOT / ".env")

_cache: dict[Path, tuple[int, dict[str, str]]] = {}


def _file_values(path: Path) -> dict[str, str]:
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _cache.get(path)
    if cached is None or cached[0] != stamp:
        loaded = {key: value for key, value in dotenv_values(path, encoding="utf-8").items() if value}
        cached = _cache[path] = (stamp, loaded)
    return cached[1]


def get_secret(name: str | None) -> str | None:
    """The value of the named variable, or ``None`` when it is unset or empty."""
    if not name:
        return None
    value = os.environ.get(name)
    if value:
        return value
    for path in ENV_FILES:
        value = _file_values(path).get(name)
        if value:
            return value
    return None


def secret_is_set(name: str | None) -> bool:
    return get_secret(name) is not None
