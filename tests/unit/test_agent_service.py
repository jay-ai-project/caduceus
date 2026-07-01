"""AgentService lifecycle (FR-A1..A6) with fakes (no real Docker/sbx)."""

import pytest

from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.common.errors import ProxyError
from caduceus.common.models import AgentKind, Lifecycle
from tests.fakes import FakeHealthChecker, FakeImageBuilder, FakeProvisioner

AIGW = "http://172.17.0.1:9701/v1"
CONFIG_PATH = "/root/.hermes/config.yaml"


def make_service(tmp_path, provisioner=None):
    reg = Registry(tmp_path / "state.json")
    reg.load()
    prov = provisioner or FakeProvisioner()
    svc = AgentService(reg, prov, FakeImageBuilder(), FakeHealthChecker(), AIGW)
    return reg, svc, prov


async def test_create_happy(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    rec = await svc.create("my-agent-1")

    assert rec.kind == AgentKind.local
    assert rec.container_name == "cad-my-agent-1"
    assert rec.endpoint and rec.endpoint.startswith("http://127.0.0.1:")
    assert rec.lifecycle == Lifecycle.running
    assert reg.get("my-agent-1") is not None
    # provider-config invariant (P-U2-3): config points at the AI-Gateway, model=default
    cfg = prov.files[("cad-my-agent-1", CONFIG_PATH)]
    assert AIGW in cfg
    assert "default" in cfg
    # token delivered via env, not argv/config
    assert prov.env["OPENAI_API_KEY"] == rec.token


async def test_create_duplicate_rejected(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    await svc.create("a")
    with pytest.raises(ProxyError):
        await svc.create("a")


async def test_create_rollback_on_failure(tmp_path):
    # put_file runs after the container is created → exercises the compensation path
    prov = FakeProvisioner(fail_on="put_file")
    reg, svc, _ = make_service(tmp_path, prov)
    with pytest.raises(ProxyError):
        await svc.create("a")
    assert reg.get("a") is None            # not persisted
    assert "cad-a" not in prov.containers  # compensated (container removed)


async def test_register_returns_guidance(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    rec, guidance = await svc.register("rem", "http://remote:9119")
    assert rec.kind == AgentKind.remote
    assert rec.lifecycle == Lifecycle.registered
    assert AIGW in guidance
    assert rec.token in guidance


async def test_remove_local_tears_down(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    await svc.create("a")
    await svc.remove("a")
    assert reg.get("a") is None
    assert "cad-a" not in prov.containers


async def test_stop_start_remote_unsupported(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    await svc.register("rem", "http://r")
    with pytest.raises(ProxyError):
        await svc.stop("rem")
    with pytest.raises(ProxyError):
        await svc.start("rem")


async def test_stop_start_local(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    await svc.create("a")
    assert (await svc.stop("a")).lifecycle == Lifecycle.stopped
    assert (await svc.start("a")).lifecycle == Lifecycle.running


async def test_start_refreshes_endpoint_after_restart(tmp_path):
    # Docker reassigns the ephemeral host port on start; `start` must refresh the
    # stored endpoint or health stays unhealthy after stop→start (U8-D5).
    reg, svc, _ = make_service(tmp_path)
    await svc.create("a")
    ep1 = reg.get("a").endpoint
    await svc.stop("a")
    rec = await svc.start("a")
    assert rec.lifecycle == Lifecycle.running
    assert rec.endpoint and rec.endpoint != ep1                 # refreshed to the new port
    assert rec.endpoint.endswith(str(rec.host_port))
    assert reg.get("a").endpoint == rec.endpoint                # persisted


# ---- U5: probe=false skips the health handshake (dashboard poll) ----
class _CountingHealth:
    def __init__(self):
        self.calls = 0

    async def check(self, rec, deep=False):
        self.calls += 1
        from caduceus.common.models import HealthLevel, HealthStatus
        return HealthStatus(HealthLevel.healthy, shallow=True)


async def test_list_probe_false_skips_health_check(tmp_path):
    reg = Registry(tmp_path / "state.json"); reg.load()
    hc = _CountingHealth()
    prov = FakeProvisioner()
    svc = AgentService(reg, prov, FakeImageBuilder(), hc, AIGW)
    await svc.create("a1")
    create_calls = hc.calls  # create does readiness + best-effort probes

    prov.calls.clear()
    await svc.list(probe=False)
    assert hc.calls == create_calls              # no extra health handshake on cheap list
    assert "statuses" not in prov.calls          # and no docker reconcile — registry-only (instant)

    await svc.list(probe=True)
    assert hc.calls == create_calls + 1          # one probe per agent when requested
    assert "statuses" in prov.calls              # full live reconcile on the authoritative path


# ---- U8: real-time single-snapshot list, async create, reconcile ----
async def test_list_probe_true_single_snapshot(tmp_path):
    # One live `docker ps` (statuses) per `list`, regardless of agent count (BR-D3).
    reg, svc, prov = make_service(tmp_path)
    await svc.create("a1")
    await svc.create("a2")
    await svc.create("a3")
    prov.calls.clear()
    await svc.list(probe=True)
    assert prov.calls.count("statuses") == 1
    assert "status" not in prov.calls            # no per-agent `docker inspect`


async def test_list_statuses_failure_keeps_lifecycle(tmp_path):
    # `docker ps` failure must not crash `agent ls` nor downgrade lifecycle (BR-D3).
    reg, svc, prov = make_service(tmp_path)
    await svc.create("a1")
    assert reg.get("a1").lifecycle == Lifecycle.running
    prov.statuses_raises = True
    recs = await svc.list(probe=True)
    assert recs[0].lifecycle == Lifecycle.running
    assert recs[0].last_health.level.value == "unknown"


async def test_create_background_returns_creating_then_ready(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    rec = await svc.create("bg", wait=False)
    assert rec.lifecycle == Lifecycle.creating          # returns immediately (BR-P4)
    # drain the scheduled background job
    await svc.await_jobs(timeout=5.0)
    assert reg.get("bg").lifecycle == Lifecycle.running  # provisioned in the background
    assert prov.files[("cad-bg", CONFIG_PATH)]           # config written


async def test_create_background_failure_marks_failed(tmp_path):
    prov = FakeProvisioner(fail_on="put_file")
    reg, svc, _ = make_service(tmp_path, prov)
    rec = await svc.create("bad", wait=False)
    assert rec.lifecycle == Lifecycle.creating
    await svc.await_jobs(timeout=5.0)
    got = reg.get("bad")
    assert got.lifecycle == Lifecycle.failed             # persisted failed (BR-P5)
    assert "create failed" in (got.last_health.detail or "")
    assert "cad-bad" not in prov.containers              # compensated


async def test_create_duplicate_inflight_rejected(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    await svc.create("dup", wait=False)                  # job in flight
    with pytest.raises(ProxyError):
        await svc.create("dup")                          # BR-P12
    await svc.await_jobs(timeout=5.0)


async def test_warm_hook_called_on_success(tmp_path):
    warmed = []

    async def warm(name):
        warmed.append(name)

    reg = Registry(tmp_path / "state.json"); reg.load()
    svc = AgentService(reg, FakeProvisioner(), FakeImageBuilder(), FakeHealthChecker(),
                       AIGW, warm_hook=warm)
    await svc.create("w1")                                # wait=True default
    assert warmed == ["w1"]                               # BR-P6


async def test_reconcile_all_reconnects_running(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    await svc.create("r1")
    # simulate a stale persisted lifecycle that reconcile should correct
    reg.get("r1").lifecycle = Lifecycle.stopped
    await svc.reconcile_all()
    assert reg.get("r1").lifecycle == Lifecycle.running  # BR-P9 (sandbox is running)
