"""ChatService — chat orchestration + session continuity (FR-C1, FR-C2).

`chat_stream(name, message)`:
  resolve AgentRecord (Registry) → **fail-fast gate** (Q4/BR-C14) → stream via the agent's
  Transport → relay events unchanged → **persist** the (possibly recreated) session id
  (Q1/BR-C1..C4). No caduceus-side turn serialization (Q2/BR-C9).

Collaborators are injected so U3 stays decoupled and unit-testable:
  - `registry`: U2 Registry (sync `get`, async `set_session`)
  - `health_check(rec, deep) -> HealthStatus`: the U2 HealthChecker (shallow gate)
  - `transport_factory(rec) -> Transport`: defaults to `Transport.for_agent`
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Optional

from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, HealthLevel, HealthStatus, Lifecycle
from caduceus.transport.base import Transport
from caduceus.transport.events import ChatEvent, ChatEventType, HistoryTurn

log = get_logger("caduceus.transport.chat")

HealthCheck = Callable[[AgentRecord, bool], Awaitable[HealthStatus]]
TransportFactory = Callable[[AgentRecord], Transport]


@dataclass
class _Pooled:
    transport: Transport
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ChatService:
    def __init__(
        self,
        registry,
        health_check: Optional[HealthCheck] = None,
        transport_factory: TransportFactory = Transport.for_agent,
        *,
        creating_retry_delay: float = 0.5,
        reuse_transport: bool = True,
    ):
        self.registry = registry
        self._health_check = health_check
        self._factory = transport_factory
        self._creating_retry_delay = creating_retry_delay
        # Reuse one open transport (and its `hermes acp` process) per agent across
        # turns, so cold-start + provider/model probing is paid once, not per turn.
        # Turns to the same agent are serialized (one stdio process). Disable for
        # the simple per-call lifecycle.
        self._reuse = reuse_transport
        self._pool: dict[str, _Pooled] = {}

    async def chat_stream(self, name: str, message: str) -> AsyncIterator[ChatEvent]:
        rec = self.registry.get(name)
        if rec is None:
            yield ChatEvent.error_(f"no such agent '{name}'", code="agent_not_found")
            return

        gate = await self._gate(rec)
        if gate is not None:
            yield gate
            return

        if not self._reuse:
            async for ev in self._stream_oneshot(rec, message):
                yield ev
            return
        async for ev in self._stream_pooled(rec, message):
            yield ev

    # ---- history replay (FR-W10; best-effort, local only) ------------
    async def history(self, name: str) -> list[HistoryTurn]:
        """Prior turns for an agent's persisted session, best-effort.

        Remote agents, sessionless agents, or any failure → `[]` (BR-W8/W9).
        Uses a dedicated short-lived transport so the pooled live-chat transport
        and its running session are never disturbed (BR-W10).
        """
        rec = self.registry.get(name)
        if rec is None or rec.kind != AgentKind.local or not rec.session_id:
            return []
        transport = self._factory(rec)
        try:
            return await transport.load_history(rec.session_id)
        except Exception as exc:  # noqa: BLE001 — best-effort; never raise to the UI
            log.info("history load error for %s: %s", name, exc)
            return []

    # ---- per-call transport (legacy / remote) ------------------------
    async def _stream_oneshot(self, rec: AgentRecord, message: str) -> AsyncIterator[ChatEvent]:
        transport = self._factory(rec)
        try:
            await transport.open()
        except Exception as exc:  # noqa: BLE001 — connect failure → terminal error
            yield ChatEvent.error_(f"could not reach agent '{rec.name}': {exc}", code="agent_unavailable")
            return
        try:
            async for ev in transport.chat_stream(rec.session_id, message):
                yield ev
        finally:
            await self._persist_session(rec, transport)
            await transport.close()

    # ---- pooled transport (local ACP; reused across turns) -----------
    async def _stream_pooled(self, rec: AgentRecord, message: str) -> AsyncIterator[ChatEvent]:
        entry = self._pool.get(rec.name)
        if entry is not None and not await entry.transport.is_alive():
            await self._evict(rec.name)
            entry = None
        if entry is None:
            entry = _Pooled(self._factory(rec))
            self._pool[rec.name] = entry

        async with entry.lock:
            try:
                await entry.transport.open()  # idempotent: no-op if already open
            except Exception as exc:  # noqa: BLE001
                await self._evict(rec.name)
                yield ChatEvent.error_(f"could not reach agent '{rec.name}': {exc}", code="agent_unavailable")
                return
            broke = False
            try:
                async for ev in entry.transport.chat_stream(rec.session_id, message):
                    if ev.type == ChatEventType.error and ev.code in ("transport_broken", "timeout"):
                        broke = True
                    yield ev
            except Exception as exc:  # noqa: BLE001 — unexpected mid-stream failure
                broke = True
                yield ChatEvent.error_(f"chat failed: {exc}", code="transport_broken")
            finally:
                await self._persist_session(rec, entry.transport)
            if broke:
                await self._evict(rec.name)  # respawn on next turn

    # ---- pool lifecycle ----------------------------------------------
    async def _evict(self, name: str) -> None:
        entry = self._pool.pop(name, None)
        if entry is not None:
            try:
                await entry.transport.close()
            except Exception as exc:  # noqa: BLE001 — best-effort
                log.debug("evict close error for %s: %s", name, exc)

    async def close_agent(self, name: str) -> None:
        """Close a pooled transport (called on agent stop/remove)."""
        await self._evict(name)

    async def close_all(self) -> None:
        """Close every pooled transport (daemon shutdown)."""
        for name in list(self._pool):
            await self._evict(name)

    # ---- fail-fast gate (Q4/BR-C14) ----------------------------------
    async def _gate(self, rec: AgentRecord) -> Optional[ChatEvent]:
        if rec.lifecycle == Lifecycle.failed:
            return ChatEvent.error_(
                f"agent '{rec.name}' is failed; check `agent ls` and recover with `agent start`",
                code="agent_unavailable",
            )
        if self._health_check is None:
            return None  # no probe wired → proceed (transport open will still fail-fast)

        hs = await self._health_check(rec, False)
        if self._healthy(hs):
            return None
        # transient: a freshly-creating agent gets one short retry before we give up.
        if rec.lifecycle == Lifecycle.creating:
            await asyncio.sleep(self._creating_retry_delay)
            hs = await self._health_check(rec, False)
            if self._healthy(hs):
                return None
        return ChatEvent.error_(
            f"agent '{rec.name}' is unavailable ({hs.detail or hs.level.value}); "
            f"check `agent ls`, recover with `agent start`",
            code="agent_unavailable",
        )

    @staticmethod
    def _healthy(hs: HealthStatus) -> bool:
        return hs.level in (HealthLevel.healthy, HealthLevel.degraded) and hs.shallow

    # ---- session continuity (Q1/BR-C1..C4) ---------------------------
    async def _persist_session(self, rec: AgentRecord, transport: Transport) -> None:
        new_id = transport.session_id
        if new_id and new_id != rec.session_id:
            if rec.session_id is None:
                log.info("agent %s: session started %s", rec.name, new_id)
            else:
                log.info("agent %s: session recreated (was %s, now %s)", rec.name, rec.session_id, new_id)
            await self.registry.set_session(rec.name, new_id)
