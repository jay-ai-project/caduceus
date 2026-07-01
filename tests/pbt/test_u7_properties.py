"""Property-based tests for U7 Performance & Stability (Hypothesis): PBT-P1..P4.

- PBT-P1 reconcile totality (BR-P2/P3): pure — any snapshot shape + any starting
  lifecycle → a valid Lifecycle, never raises; `creating` is never downgraded.
- PBT-P2 async state machine (BR-P4/P5/P6): background create → running on success,
  failed on any injected failure, never stopped.
- PBT-P3 single-snapshot invariant (BR-P1): `list(probe=True)` makes exactly one
  `sbx ls` (list_statuses) regardless of N; `probe=False` makes zero.
- PBT-P4 shutdown safety (BR-P8): the agent-side shutdown path never stops/removes
  a sandbox.

Async properties follow the repo pattern: a sync `@given` body that drives the real
AgentService via `asyncio.run` (keeps Hypothesis and pytest-asyncio from clashing).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from caduceus.agents.provisioner import SandboxSnapshot
from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle
from tests.fakes import FakeHealthChecker, FakeImageBuilder, FakeProvisioner

AIGW = "http://172.17.0.1:9701/v1"


def _tmp_state() -> str:
    return os.path.join(tempfile.mkdtemp(), "state.json")


def _make_service():
    reg = Registry(_tmp_state())
    reg.load()
    prov = FakeProvisioner()
    svc = AgentService(reg, prov, FakeImageBuilder(), FakeHealthChecker(), AIGW)
    return reg, svc, prov


# ---- PBT-P1: reconcile totality (pure) --------------------------------
_status_vals = st.sampled_from(["running", "stopped", "missing", "weird", "", "Running"])
_lifecycles = st.sampled_from(list(Lifecycle))


@given(present=st.booleans(), stval=_status_vals, start=_lifecycles)
def test_pbt_p1_reconcile_totality(present, stval, start):
    rec = AgentRecord(name="x", kind=AgentKind.local, token="t",
                      sandbox_name="cad-x", lifecycle=start)
    statuses = {"cad-x": stval} if present else {}
    AgentService._reconcile_lifecycle(rec, SandboxSnapshot(statuses, ok=True))
    assert isinstance(rec.lifecycle, Lifecycle)
    if start == Lifecycle.creating:
        assert rec.lifecycle == Lifecycle.creating  # never downgraded (BR-P3)
    elif present and stval == "running":
        assert rec.lifecycle == Lifecycle.running
    elif present and stval == "stopped":
        assert rec.lifecycle == Lifecycle.stopped
    else:  # absent or any other runtime string → missing → failed
        assert rec.lifecycle == Lifecycle.failed


# ---- PBT-P2: async create state machine -------------------------------
@settings(max_examples=20, deadline=None)
@given(fail_on=st.sampled_from([None, "create_sandbox", "write_file"]))
def test_pbt_p2_async_state_machine(fail_on):
    async def _run():
        reg = Registry(_tmp_state()); reg.load()
        prov = FakeProvisioner(fail_on=fail_on)
        svc = AgentService(reg, prov, FakeImageBuilder(), FakeHealthChecker(), AIGW)
        rec = await svc.create("m", wait=False)
        assert rec.lifecycle == Lifecycle.creating  # returns immediately (BR-P4)
        await svc.await_jobs(timeout=5.0)
        final = reg.get("m").lifecycle
        assert final != Lifecycle.stopped            # never silently stopped
        assert final == (Lifecycle.running if fail_on is None else Lifecycle.failed)

    asyncio.run(_run())


# ---- PBT-P3: single-snapshot invariant --------------------------------
@settings(max_examples=30, deadline=None)
@given(n=st.integers(min_value=0, max_value=5), probe=st.booleans())
def test_pbt_p3_single_snapshot(n, probe):
    async def _run():
        reg, svc, prov = _make_service()
        for i in range(n):
            await svc.create(f"a{i}")
        prov.calls.clear()
        await svc.list(probe=probe)
        # Exactly one `sbx ls` when probing with ≥1 local agent; zero otherwise
        # (probe=False, or no local agents to reconcile) — never O(N).
        expected = 1 if (probe and n >= 1) else 0
        assert prov.calls.count("list_statuses") == expected
        assert "status" not in prov.calls  # never a per-agent re-probe

    asyncio.run(_run())


# ---- PBT-P4: shutdown never stops sandboxes ---------------------------
@settings(max_examples=20, deadline=None)
@given(n=st.integers(min_value=0, max_value=4))
def test_pbt_p4_shutdown_never_stops_sandboxes(n):
    async def _run():
        reg, svc, prov = _make_service()
        for i in range(n):
            await svc.create(f"a{i}")
        prov.calls.clear()
        # agent-side of the daemon shutdown sequence (BR-P8): settle in-flight jobs.
        # (Pooled `hermes acp` stdio teardown is ChatService.close_all — stdio only.)
        await svc.await_jobs(timeout=1.0)
        assert "stop" not in prov.calls
        assert "remove" not in prov.calls

    asyncio.run(_run())
