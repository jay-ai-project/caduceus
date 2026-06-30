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
from typing import Optional

from caduceus.common.logging import get_logger
from caduceus.common.models import AgentRecord, HealthLevel, HealthStatus, Lifecycle
from caduceus.transport.base import Transport
from caduceus.transport.events import ChatEvent

log = get_logger("caduceus.transport.chat")

HealthCheck = Callable[[AgentRecord, bool], Awaitable[HealthStatus]]
TransportFactory = Callable[[AgentRecord], Transport]


class ChatService:
    def __init__(
        self,
        registry,
        health_check: Optional[HealthCheck] = None,
        transport_factory: TransportFactory = Transport.for_agent,
        *,
        creating_retry_delay: float = 0.5,
    ):
        self.registry = registry
        self._health_check = health_check
        self._factory = transport_factory
        self._creating_retry_delay = creating_retry_delay

    async def chat_stream(self, name: str, message: str) -> AsyncIterator[ChatEvent]:
        rec = self.registry.get(name)
        if rec is None:
            yield ChatEvent.error_(f"no such agent '{name}'", code="agent_not_found")
            return

        gate = await self._gate(rec)
        if gate is not None:
            yield gate
            return

        transport = self._factory(rec)
        try:
            await transport.open()
        except Exception as exc:  # noqa: BLE001 — connect failure → terminal error
            yield ChatEvent.error_(f"could not reach agent '{name}': {exc}", code="agent_unavailable")
            return

        try:
            async for ev in transport.chat_stream(rec.session_id, message):
                yield ev
        finally:
            await self._persist_session(rec, transport)
            await transport.close()

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
