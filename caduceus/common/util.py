"""Small shared helpers used across units (U10 consolidation)."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Current UTC time in ISO-8601 (the registry/serialization timestamp format)."""
    return datetime.now(timezone.utc).isoformat()


async def call_maybe_async(fn, /, *args, **kwargs):
    """Invoke a sync-or-async callable uniformly; None fn is a no-op.

    Used for injected hooks (progress reporters, warm hooks) that callers may
    supply as either plain functions or coroutines.
    """
    if fn is None:
        return None
    res = fn(*args, **kwargs)
    if hasattr(res, "__await__"):
        return await res
    return res


def make_emit(progress):
    """Wrap an optional `progress(phase, detail="")` hook into an awaitable emitter."""
    async def _emit(phase: str, detail: str = "") -> None:
        await call_maybe_async(progress, phase, detail)
    return _emit
