"""EventBus — in-process pub/sub powering the Web UI's `/api/events` SSE stream (U9).

Replaces the dashboard's 3s polling with server push. State producers (the
Registry on any mutation, the Supervisor after each health sweep) call `notify()`;
each connected browser gets a fresh **snapshot** (`status` + `agents`, the exact
data the old `/status` + `/agents?probe=false` polls returned).

Design notes:
  - **Coalescing** per subscriber: only the latest snapshot is retained, so a slow
    client can never grow the daemon's memory or fall behind — it just skips to the
    newest state (dashboards only care about "now", not every intermediate frame).
  - **Snapshot on connect**: `subscribe()` yields the current state immediately so a
    freshly-loaded page paints without waiting for the next change.
  - **Keepalive**: yields `None` on idle so the endpoint can emit an SSE comment,
    keeping the connection warm and surfacing dead clients for cleanup.
  - **Fault-isolated**: a failing snapshot build never propagates into a producer
    (a broadcast must never break `registry.upsert` or the supervisor loop).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Optional

from caduceus.common.logging import get_logger

log = get_logger("caduceus.daemon.events")

#: seconds of idle before `subscribe()` emits a keepalive tick (None).
KEEPALIVE_S = 15.0

SnapshotProvider = Callable[[], Awaitable[dict]]


class _Subscriber:
    """A single connected client. Holds only the *latest* snapshot (coalescing)."""

    def __init__(self) -> None:
        self._latest: Optional[dict] = None
        self._event = asyncio.Event()

    def push(self, item: dict) -> None:
        self._latest = item
        self._event.set()

    async def get(self) -> dict:
        await self._event.wait()
        self._event.clear()
        item = self._latest
        self._latest = None
        return item  # type: ignore[return-value]


class EventBus:
    def __init__(self, snapshot_provider: SnapshotProvider) -> None:
        self._snapshot = snapshot_provider
        self._subs: set[_Subscriber] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def notify(self) -> None:
        """Broadcast the current snapshot to every connected client.

        No-op when nobody is listening (so producers pay nothing on an idle daemon).
        Never raises — a snapshot-build failure is logged and swallowed.
        """
        if not self._subs:
            return
        try:
            snap = await self._snapshot()
        except Exception as exc:  # noqa: BLE001 — a broadcast must not break producers
            log.warning("event snapshot build failed: %s", exc)
            return
        for sub in list(self._subs):
            sub.push(snap)

    async def subscribe(self, keepalive: float = KEEPALIVE_S) -> AsyncIterator[Optional[dict]]:
        """Yield snapshots for one client: the current state, then each change.

        Yields `None` after `keepalive` seconds of idle so the caller can send an
        SSE keepalive comment. The subscriber is always unregistered on exit
        (client disconnect cancels the generator → `finally`).
        """
        sub = _Subscriber()
        self._subs.add(sub)
        try:
            try:
                yield await self._snapshot()  # immediate snapshot on connect
            except Exception as exc:  # noqa: BLE001 — still serve live updates if the first build fails
                log.warning("initial event snapshot failed: %s", exc)
            while True:
                try:
                    yield await asyncio.wait_for(sub.get(), timeout=keepalive)
                except asyncio.TimeoutError:
                    yield None  # keepalive tick
        finally:
            self._subs.discard(sub)
