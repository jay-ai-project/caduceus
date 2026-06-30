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
    assert rec.sandbox_name == "cad-my-agent-1"
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
    # write_file runs after the sandbox is created → exercises the compensation path
    prov = FakeProvisioner(fail_on="write_file")
    reg, svc, _ = make_service(tmp_path, prov)
    with pytest.raises(ProxyError):
        await svc.create("a")
    assert reg.get("a") is None          # not persisted
    assert "cad-a" not in prov.sandboxes  # compensated (sandbox removed)


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
    assert "cad-a" not in prov.sandboxes


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
