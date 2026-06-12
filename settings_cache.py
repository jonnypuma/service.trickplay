"""Short-lived cache for addon settings reads on hot paths."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

CACHE_TTL_SEC = 2.0
_cache: dict[str, tuple[object, float]] = {}


def get_cached(key: str, factory: Callable[[], T]) -> T:
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None:
        value, cached_at = entry
        if now - cached_at < CACHE_TTL_SEC:
            return value  # type: ignore[return-value]
    value = factory()
    _cache[key] = (value, now)
    return value


def invalidate_settings_cache() -> None:
    _cache.clear()
