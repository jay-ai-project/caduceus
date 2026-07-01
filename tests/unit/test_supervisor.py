"""U3 — Supervisor: restart/back-off/circuit, remote-no-restart, fault isolation."""

from __future__ import annotations

from caduceus.common.models import AgentKind, HealthLevel, HealthStatus
from caduceus.transport.supervisor import CircuitState, Supervisor

from tests.fakes import make_agent


class Harness:
    """Controllable collaborators + a virtual clock to drive Supervisor._sweep."""

    def __init__(self, kind: AgentKind = AgentKind.local):
        self.rec = make_agent(kind=kind)
        self.t = 0.0
        self.healthy = True
        self.restart_ok = True
        self.health_raises = False
        self.restarts = 0
        self.failed: list[str] = []
        self.sup = Supervisor(
            list_agents=lambda: [self.rec],
            health_check=self._health,
            restart=self._restart,
            mark_failed=self._mark,
            clock=lambda: self.t,
            fail_threshold=2,
            restart_threshold=3,
            backoff=(5.0, 15.0, 45.0, 120.0),
        )

    async def _health(self, rec, deep):
        if self.health_raises:
            raise RuntimeError("probe blew up")
        lvl = HealthLevel.healthy if self.healthy else HealthLevel.unhealthy
        return HealthStatus(lvl, shallow=self.healthy)

    async def _restart(self, rec):
        self.restarts += 1
        if not self.restart_ok:
            raise RuntimeError("restart failed")

    async def _mark(self, name):
        self.failed.append(name)

    async def sweep(self, advance: float = 1000.0):
        self.t += advance
        await self.sup._sweep()

    def state(self):
        return self.sup.state_of(self.rec.name)


async def test_healthy_no_restart():
    h = Harness()
    for _ in range(3):
        await h.sweep()
    assert h.restarts == 0
    assert h.state().circuit == CircuitState.closed


async def test_non_running_agent_not_supervised():
    # A `creating`/`stopped`/`failed` agent is skipped entirely (BR-P11), so an
    # unhealthy probe never triggers a restart that would fight the provisioner.
    from caduceus.common.models import Lifecycle

    for lc in (Lifecycle.creating, Lifecycle.stopped, Lifecycle.failed):
        h = Harness()
        h.rec.lifecycle = lc
        h.healthy = False
        for _ in range(4):
            await h.sweep()
        assert h.restarts == 0
        assert h.state() is None  # no supervision state created for a skipped agent


async def test_local_unhealthy_restarts_after_threshold():
    h = Harness()
    h.healthy = False
    await h.sweep()  # failure 1 → no restart yet
    assert h.restarts == 0
    await h.sweep()  # failure 2 → restart
    assert h.restarts == 1


async def test_circuit_opens_and_marks_failed():
    h = Harness()
    h.healthy = False
    for _ in range(6):
        await h.sweep()  # advance past back-off each time
    assert h.restarts == 3
    assert h.state().circuit == CircuitState.open
    assert h.failed == [h.rec.name]
    # once open, no further restarts
    before = h.restarts
    await h.sweep()
    assert h.restarts == before


async def test_backoff_gate_blocks_immediate_retry():
    h = Harness()
    h.healthy = False
    await h.sweep()                 # failure 1
    await h.sweep(advance=1000.0)   # failure 2 → restart #1, schedules next_attempt
    assert h.restarts == 1
    await h.sweep(advance=0.0)      # no time passed → gated, no restart
    assert h.restarts == 1


async def test_recovery_resets_state():
    h = Harness()
    h.healthy = False
    await h.sweep()
    await h.sweep()  # one restart, some failures
    assert h.state().consecutive_health_failures >= 1
    h.healthy = True
    await h.sweep()
    st = h.state()
    assert st.consecutive_health_failures == 0
    assert st.restart_attempts == 0
    assert st.circuit == CircuitState.closed


async def test_remote_never_restarts():
    h = Harness(kind=AgentKind.remote)
    h.healthy = False
    for _ in range(6):
        await h.sweep()
    assert h.restarts == 0
    assert h.failed == []


async def test_health_probe_exception_is_isolated():
    h = Harness()
    h.health_raises = True
    # treated as unhealthy; must not raise out of the sweep
    for _ in range(2):
        await h.sweep()
    assert h.restarts >= 1  # progressed to a restart attempt without crashing


async def test_reset_agent_clears_circuit():
    h = Harness()
    h.healthy = False
    for _ in range(6):
        await h.sweep()
    assert h.state().circuit == CircuitState.open
    h.sup.reset_agent(h.rec.name)
    assert h.state().circuit == CircuitState.closed
