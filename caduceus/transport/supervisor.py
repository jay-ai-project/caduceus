"""Supervisor — process supervision for managed agents (RES-5, BR-S1..S7).

A periodic background sweep runs deep health per agent and, for **local** agents,
restarts a dead `hermes serve` with exponential back-off and a circuit breaker.
**Remote** agents are probe/reconnect-only — never restarted (BR-A10/BR-S1).

Collaborators are injected callables so U3 stays decoupled (U4 wires the real U2
Provisioner/Registry/HealthChecker at composition time):
  - `list_agents() -> list[AgentRecord]`        (sync or async)
  - `health_check(rec, deep) -> HealthStatus`   (deep probe; no LLM spend)
  - `restart(rec) -> None`                      (relaunch local serve; raises on failure)
  - `mark_failed(name) -> None`                 (persist Lifecycle.failed)

The sweep loop is fault-isolated: any probe/restart exception is logged and treated as
a failed check; it never breaks the loop or crashes the daemon (RES-4/BR-S7).
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from caduceus.common.logging import get_logger
from caduceus.common.models import AgentKind, AgentRecord, HealthLevel, HealthStatus

log = get_logger("caduceus.transport.supervisor")

#: exponential back-off schedule (seconds); the last value is the cap.
DEFAULT_BACKOFF = (5.0, 15.0, 45.0, 120.0)


class CircuitState(str, Enum):
    closed = "closed"
    open = "open"


@dataclass
class AgentSupervisionState:
    agent_name: str
    consecutive_health_failures: int = 0
    restart_attempts: int = 0
    backoff_index: int = 0
    next_attempt_at: Optional[float] = None
    circuit: CircuitState = CircuitState.closed

    def reset(self) -> None:
        self.consecutive_health_failures = 0
        self.restart_attempts = 0
        self.backoff_index = 0
        self.next_attempt_at = None
        self.circuit = CircuitState.closed


ListAgents = Callable[[], object]
HealthCheck = Callable[[AgentRecord, bool], Awaitable[HealthStatus]]
Restart = Callable[[AgentRecord], Awaitable[None]]
MarkFailed = Callable[[str], Awaitable[None]]


class Supervisor:
    def __init__(
        self,
        list_agents: ListAgents,
        health_check: HealthCheck,
        restart: Restart,
        mark_failed: MarkFailed,
        *,
        interval: float = 30.0,
        fail_threshold: int = 2,
        restart_threshold: int = 3,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._list_agents = list_agents
        self._health_check = health_check
        self._restart = restart
        self._mark_failed = mark_failed
        self.interval = interval
        self.fail_threshold = fail_threshold
        self.restart_threshold = restart_threshold
        self.backoff = backoff
        self._clock = clock
        self._states: dict[str, AgentSupervisionState] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ---- lifecycle ---------------------------------------------------
    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="caduceus-supervisor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                log.warning("supervisor sweep error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    # ---- one sweep pass (also directly callable in tests) ------------
    async def _sweep(self) -> None:
        for rec in await self._agents():
            state = self._states.setdefault(rec.name, AgentSupervisionState(rec.name))
            healthy = await self._is_healthy(rec)
            if healthy:
                state.reset()
                continue
            # unhealthy
            if rec.kind == AgentKind.remote:
                # probe/reconnect only — never restart (BR-A10/BR-S1)
                continue
            await self._handle_local_unhealthy(rec, state)

    async def _handle_local_unhealthy(self, rec: AgentRecord, state: AgentSupervisionState) -> None:
        state.consecutive_health_failures += 1
        if state.circuit == CircuitState.open:
            return  # circuit open ⇒ no further restart attempts (BR-S5)
        if state.consecutive_health_failures < self.fail_threshold:
            return  # not yet (≥2 needed; BR-S3)
        now = self._clock()
        if state.next_attempt_at is not None and now < state.next_attempt_at:
            return  # back-off gate (BR-S4)

        try:
            await self._restart(rec)
            log.info("supervisor: restarted agent %s (attempt %d)", rec.name, state.restart_attempts + 1)
        except Exception as exc:  # noqa: BLE001 — restart failure is just a failed attempt
            log.warning("supervisor: restart of %s failed: %s", rec.name, exc)

        state.restart_attempts += 1
        delay = self.backoff[min(state.backoff_index, len(self.backoff) - 1)]
        state.backoff_index += 1
        state.next_attempt_at = now + delay

        if state.restart_attempts >= self.restart_threshold:
            state.circuit = CircuitState.open
            try:
                await self._mark_failed(rec.name)
            except Exception as exc:  # noqa: BLE001
                log.warning("supervisor: mark_failed(%s) error: %s", rec.name, exc)
            log.warning("supervisor: circuit OPEN for %s after %d restart attempts", rec.name, state.restart_attempts)

    # ---- manual recovery (called by U4 on `agent start`) -------------
    def reset_agent(self, name: str) -> None:
        st = self._states.get(name)
        if st is not None:
            st.reset()

    # ---- helpers -----------------------------------------------------
    async def _agents(self) -> list[AgentRecord]:
        res = self._list_agents()
        if inspect.isawaitable(res):
            res = await res
        return list(res)

    async def _is_healthy(self, rec: AgentRecord) -> bool:
        try:
            hs = await self._health_check(rec, True)
        except Exception as exc:  # noqa: BLE001 — probe failure == unhealthy
            log.debug("supervisor: health probe of %s raised: %s", rec.name, exc)
            return False
        # Cache the snapshot so cheap (no-probe) listings — e.g. the Web UI
        # dashboard poll — can show fresh health without re-handshaking (NFR-W3).
        rec.last_health = hs
        return hs.level == HealthLevel.healthy

    def state_of(self, name: str) -> Optional[AgentSupervisionState]:
        return self._states.get(name)
