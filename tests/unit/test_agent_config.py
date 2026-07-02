"""U10/R9 — real `agent config` over the container's HERMES_HOME.

Codec unit tests + the wiring closures (read/write/reload) against FakeProvisioner.
"""

from __future__ import annotations

from caduceus.agents.hermes_config import render_hermes_config
from caduceus.common.dto import ConfigChange, ConfigSnapshot
from caduceus.config import agent_config as ac
from caduceus.config.editor import ConfigEditor
from caduceus.config.service import ConfigService
from caduceus.daemon.wiring import _make_read_config, _make_reload, _make_write_config

from tests.fakes import FakeHealthChecker, FakeProvisioner, FakeRegistry, make_agent

AIGW = "http://172.17.0.1:9701/v1"


# ---- codec ----------------------------------------------------------
def test_snapshot_of_rendered_config():
    text = render_hermes_config(AIGW, "default", api_key="sekrit", workspace="/opt/data/workspace")
    snap = ac.snapshot_of(text, "I am a soul", ["skill-a"])
    assert "terminal" in snap.tools_enabled          # rendered toolset list surfaced
    assert "tts" in snap.tools_disabled              # known-but-not-enabled
    assert snap.soul == "I am a soul"
    assert snap.skills == ["skill-a"]
    # protected keys (incl. the api_key secret) never reach the core view
    assert not any(k.startswith("model") for k in snap.core)
    assert "sekrit" not in str(snap.core)


def test_merge_snapshot_preserves_protected_keys():
    text = render_hermes_config(AIGW, "default", api_key="sekrit")
    snap = ac.snapshot_of(text, "", [])
    snap.tools_enabled = [t for t in snap.tools_enabled if t != "browser"]
    snap.core["agent.max_turns"] = "100"
    merged = ac.merge_snapshot(text, snap)
    doc = ac.parse_config(merged)
    assert doc["model"]["api_key"] == "sekrit"       # caduceus-owned keys intact
    assert doc["model"]["base_url"] == AIGW
    assert doc["approvals"]["mode"] == "off"
    assert "browser" not in doc["platform_toolsets"]["api_server"]
    assert doc["agent"]["max_turns"] == 100          # yaml-parsed scalar


def test_core_scalar_round_trip_for_verification():
    # write parses with yaml.safe_load; read stringifies with safe_dump → equal text
    for raw in ("100", "true", "false", "3.5", "hello"):
        merged = ac.merge_snapshot("", ConfigSnapshot(core={"agent.x": raw}))
        back = ac.snapshot_of(merged, "", [])
        assert back.core["agent.x"] == raw


def test_validate_change_rules():
    assert ac.validate_change(ConfigChange(add_skills=["s"])) is not None      # no authored content
    assert ac.validate_change(ConfigChange(remove_skills=["../etc"])) is not None
    assert ac.validate_change(ConfigChange(enable_tools=["not-a-toolset"])) is not None
    assert ac.validate_change(ConfigChange(set_core={"model.api_key": "x"})) is not None
    assert ac.validate_change(ConfigChange(set_core={"terminal.cwd": "/x"})) is not None
    assert ac.validate_change(ConfigChange(
        remove_skills=["ok-skill"], enable_tools=["tts"], disable_tools=["browser"],
        soul="new", set_core={"agent.max_turns": "99"})) is None


# ---- wiring closures against FakeProvisioner ------------------------
def _service(prov):
    reg = FakeRegistry([make_agent(name="a1")])
    editor = ConfigEditor(
        read_config=_make_read_config(prov),
        write_config=_make_write_config(prov),
        reload_agent=_make_reload(prov, reg, _noop_close),
        health_check=FakeHealthChecker().check,
        validate_change=ac.validate_change,
    )
    return reg, ConfigService(reg, editor)


async def _noop_close(name):
    return None


def _seed(prov, cn="cad-a1"):
    prov.containers[cn] = "running"
    prov.configs[cn] = render_hermes_config(AIGW, "default", api_key="sekrit",
                                            workspace="/opt/data/workspace")
    prov.skill_dirs = {cn: {"old-skill"}}
    prov.ports[cn] = 49001
    prov._next_port = 50000  # a restart must visibly reassign the published port


async def test_get_config_reads_real_state():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    snap = await svc.get_config("a1")
    assert snap.skills == ["old-skill"]
    assert "terminal" in snap.tools_enabled
    assert "sekrit" not in str(snap.to_dict())       # secret-free projection


async def test_set_soul_is_hot_and_verified():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    res = await svc.set_config("a1", ConfigChange(soul="Be kind."))
    assert res.verified is True
    assert res.strategy == "hot_reload"
    from caduceus.agents.provisioner import SOUL_PATH
    assert prov.files[("cad-a1", SOUL_PATH)] == "Be kind."
    assert prov.containers["cad-a1"] == "running"    # no restart for soul


async def test_disable_tool_restarts_and_refreshes_endpoint():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    old_endpoint = reg.get("a1").endpoint
    res = await svc.set_config("a1", ConfigChange(disable_tools=["browser"]))
    assert res.verified is True
    assert res.strategy == "restart_serve"
    doc = ac.parse_config(prov.configs["cad-a1"])
    assert "browser" not in doc["platform_toolsets"]["api_server"]
    assert doc["model"]["api_key"] == "sekrit"       # merge preserved the secret
    assert reg.get("a1").endpoint != old_endpoint    # port reassigned on restart


async def test_remove_skill_deletes_dir():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    res = await svc.set_config("a1", ConfigChange(remove_skills=["old-skill"]))
    assert res.verified is True
    assert prov.skill_dirs["cad-a1"] == set()


async def test_add_skill_rejected_with_guidance():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    res = await svc.set_config("a1", ConfigChange(add_skills=["new-skill"]))
    assert res.verified is False
    assert "not supported" in res.detail
    assert prov.skill_dirs["cad-a1"] == {"old-skill"}  # nothing written


async def test_protected_core_key_rejected():
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    res = await svc.set_config("a1", ConfigChange(set_core={"model.base_url": "http://evil"}))
    assert res.verified is False
    assert "managed by caduceus" in res.detail
    assert AIGW in prov.configs["cad-a1"]            # untouched

async def test_restart_serve_refreshes_dashboard_port():
    """U11/BR-DB4: a config restart reassigns the dashboard's published port too."""
    prov = FakeProvisioner()
    _seed(prov)
    reg, svc = _service(prov)
    rec = reg.get("a1")
    rec.dashboard_password = "pw"
    rec.dashboard_port = 41111
    prov.published_dashboard["cad-a1"] = True
    res = await svc.set_config("a1", ConfigChange(disable_tools=["browser"]))
    assert res.strategy == "restart_serve"
    assert reg.get("a1").dashboard_port == prov.dashboard_ports["cad-a1"]
    assert reg.get("a1").dashboard_port != 41111
