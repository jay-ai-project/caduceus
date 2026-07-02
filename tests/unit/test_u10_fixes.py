"""U10 review-remediation regressions (R1–R8; see aidlc-docs/reviews/2026-07-02)."""

from __future__ import annotations

import httpx
import pytest

from caduceus.agents.registry import Registry
from caduceus.agents.service import AgentService
from caduceus.cli.client import ControlAPIClient, ControlError
from caduceus.common.dto import AgentView
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle
from caduceus.common.settings import Settings
from caduceus.transport.hermes_api import HermesApiTransport

from tests.fakes import FakeHealthChecker, FakeImageBuilder, FakeProvisioner

AIGW = "http://172.17.0.1:9701/v1"


def make_service(tmp_path, provisioner=None):
    reg = Registry(tmp_path / "state.json")
    reg.load()
    prov = provisioner or FakeProvisioner()
    svc = AgentService(reg, prov, FakeImageBuilder(), FakeHealthChecker(), AIGW)
    return reg, svc, prov


# ---- R1: /status carries live upstream + uptime -------------------
async def test_status_snapshot_populates_upstream_and_uptime(tmp_path):
    from caduceus.daemon.wiring import build_services

    settings = Settings(upstream_base_url="http://127.0.0.1:1",  # nothing listens here
                        default_model="m")
    services = build_services(settings, state_dir=tmp_path)
    gs = await services.status_snapshot()
    assert gs.running is True
    assert gs.upstream == "unhealthy"      # probe ran (no longer hardwired "unknown")
    assert gs.uptime_s is not None and gs.uptime_s >= 0


# ---- R3: orphaned `creating` records are failed at boot ------------
async def test_boot_reconcile_fails_orphaned_creating(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    rec = AgentRecord(name="zomb", kind=AgentKind.local, token="t",
                      container_name="cad-zomb", lifecycle=Lifecycle.creating)
    await reg.upsert(rec)
    prov.containers["cad-zomb"] = "created"  # half-provisioned leftover

    await svc.reconcile_all()

    got = reg.get("zomb")
    assert got.lifecycle == Lifecycle.failed
    assert "mid-provision" in got.last_health.detail
    assert "cad-zomb" not in prov.containers  # compensated


async def test_boot_reconcile_fails_creating_without_container(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    await reg.upsert(AgentRecord(name="zomb2", kind=AgentKind.local, token="t",
                                 container_name="cad-zomb2", lifecycle=Lifecycle.creating))
    await svc.reconcile_all()
    assert reg.get("zomb2").lifecycle == Lifecycle.failed


# ---- R4: CLI streams have no read timeout + httpx errors → ControlError ----
class _CapturingClient:
    def __init__(self, exc):
        self.exc = exc
        self.kwargs = None

    def stream(self, *args, **kwargs):
        self.kwargs = kwargs
        raise self.exc


def test_chat_stream_wraps_httpx_error_and_unsets_read_timeout():
    stub = _CapturingClient(httpx.ConnectError("boom"))
    c = ControlAPIClient(client=stub)
    with pytest.raises(ControlError):
        list(c.chat("a1", "hi"))
    assert stub.kwargs["timeout"].read is None  # no mid-stream read timeout


def test_logs_stream_wraps_httpx_error():
    stub = _CapturingClient(httpx.ReadTimeout("slow"))
    c = ControlAPIClient(client=stub)
    with pytest.raises(ControlError):
        list(c.logs("a1", follow=True))
    assert stub.kwargs["timeout"].read is None


# ---- R5: create --model/--image are honoured -----------------------
async def test_create_model_and_image_are_applied(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    rec = await svc.create("m1", model="llama3:8b", image="custom/agent:v1")

    assert rec.model_alias == "llama3:8b"
    assert svc.images.built == ["custom/agent:v1"]          # per-create image override
    assert "default: llama3:8b" in prov.configs["cad-m1"]   # rendered into hermes config


async def test_create_defaults_when_no_overrides(tmp_path):
    reg, svc, prov = make_service(tmp_path)
    rec = await svc.create("m2")
    assert rec.model_alias == "default"
    assert svc.images.built == [svc.image_tag]


# ---- R6: register --auth is stored and used as the transport bearer ----
async def test_register_auth_stored_and_secret(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    rec, guidance = await svc.register("rem", "http://remote:8642", auth="their-key")
    assert rec.serve_auth == "their-key"
    assert "existing bearer key" in guidance          # own-auth guidance branch
    assert "serve_auth" not in AgentView.from_record(rec).to_dict()  # never projected


async def test_register_without_auth_keeps_single_token(tmp_path):
    reg, svc, _ = make_service(tmp_path)
    rec, guidance = await svc.register("rem2", "http://remote:8642")
    assert rec.serve_auth is None
    assert rec.token in guidance                      # minted token doubles as key


def test_transport_bearer_prefers_serve_auth():
    rec = AgentRecord(name="r", kind=AgentKind.remote, token="minted",
                      endpoint="http://remote:8642", serve_auth="their-key")
    t = HermesApiTransport(rec)
    assert t._new_client().headers["authorization"] == "Bearer their-key"


def test_agent_record_round_trips_serve_auth():
    rec = AgentRecord(name="r", kind=AgentKind.remote, token="t", serve_auth="k")
    assert AgentRecord.from_dict(rec.to_dict()) == rec


# ---- R7: a successful final restart is NOT failed by the circuit ----
async def test_supervisor_successful_last_restart_recovers():
    from caduceus.common.models import HealthLevel, HealthStatus
    from caduceus.transport.supervisor import CircuitState, Supervisor
    from tests.fakes import make_agent

    rec = make_agent()
    healthy = {"v": False}
    restarts = []
    failed = []

    async def health(r, deep):
        lvl = HealthLevel.healthy if healthy["v"] else HealthLevel.unhealthy
        return HealthStatus(lvl, shallow=healthy["v"])

    async def restart(r):
        restarts.append(r.name)
        healthy["v"] = True  # the (last) restart actually fixes the agent

    async def mark_failed(name):
        failed.append(name)

    t = {"v": 0.0}
    sup = Supervisor(lambda: [rec], health, restart, mark_failed,
                     fail_threshold=1, restart_threshold=1,
                     clock=lambda: t["v"], backoff=(5.0,))

    t["v"] += 1000; await sup._sweep()   # unhealthy → restart #1 (budget now spent) → heals
    t["v"] += 1000; await sup._sweep()   # healthy again → state resets, NO circuit open
    assert restarts == [rec.name]
    assert failed == []
    assert sup.state_of(rec.name).circuit == CircuitState.closed
    assert sup.state_of(rec.name).restart_attempts == 0


async def test_supervisor_circuit_opens_when_budget_spent_and_still_unhealthy():
    from caduceus.common.models import HealthLevel, HealthStatus
    from caduceus.transport.supervisor import CircuitState, Supervisor
    from tests.fakes import make_agent

    rec = make_agent()
    restarts = []
    failed = []

    async def health(r, deep):
        return HealthStatus(HealthLevel.unhealthy, shallow=False)

    async def restart(r):
        restarts.append(r.name)

    async def mark_failed(name):
        failed.append(name)

    t = {"v": 0.0}
    sup = Supervisor(lambda: [rec], health, restart, mark_failed,
                     fail_threshold=1, restart_threshold=1,
                     clock=lambda: t["v"], backoff=(5.0,))

    t["v"] += 1000; await sup._sweep()   # restart #1 (budget spent), still unhealthy
    t["v"] += 1000; await sup._sweep()   # a further restart would be needed → circuit opens
    assert restarts == [rec.name]        # no second restart
    assert failed == [rec.name]
    assert sup.state_of(rec.name).circuit == CircuitState.open


# ---- R8: corrupt state.json → backup + empty registry, not a crash ----
def test_registry_load_tolerates_corrupt_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json at all", encoding="utf-8")
    reg = Registry(path)
    reg.load()  # must not raise
    assert reg.list() == []
    backups = list(tmp_path.glob("state.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8").startswith("{not json")
