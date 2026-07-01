"""U4 — CLI handlers via typer CliRunner + FakeControlAPIClient."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from caduceus.cli import app as cli_app
from caduceus.cli.client import ControlError
from caduceus.common.dto import AgentView, GatewayStatus

from tests.fakes import FakeControlAPIClient

runner = CliRunner()


def _patch_client(monkeypatch, **kw):
    fake = FakeControlAPIClient(**kw)
    monkeypatch.setattr(cli_app, "get_client", lambda: fake)
    return fake


def _patch_gateway(monkeypatch, status):
    class _GW:
        def status(self):
            return status

        def stop(self):
            return None

    monkeypatch.setattr(cli_app, "get_gateway", lambda: _GW())


def test_agent_ls_human(monkeypatch):
    _patch_client(monkeypatch, agents=[AgentView("a1", "local", "running", "healthy")])
    res = runner.invoke(cli_app.app, ["agent", "ls"])
    assert res.exit_code == 0
    assert "a1" in res.stdout and "NAME" in res.stdout


def test_agent_ls_json(monkeypatch):
    _patch_client(monkeypatch, agents=[AgentView("a1", "local", "running", "healthy")])
    res = runner.invoke(cli_app.app, ["agent", "ls", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data[0]["name"] == "a1"


def test_daemon_down_exit_code(monkeypatch):
    _patch_client(monkeypatch, up=False)
    res = runner.invoke(cli_app.app, ["agent", "ls"])
    assert res.exit_code == 1
    assert "not running" in (res.stdout + str(res.stderr)).lower()


def test_agent_create_background_default(monkeypatch):
    # default: create returns immediately; provisioning continues in the background
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "create", "new1"])
    assert res.exit_code == 0
    assert "creating agent 'new1' in the background" in res.stdout
    assert "creating container" not in res.output  # no blocking provisioning progress


def test_agent_create_wait(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "create", "new1", "--wait"])
    assert res.exit_code == 0
    assert "created agent 'new1'" in res.stdout
    assert "creating container" in res.output      # provisioning progress shown


def test_agent_create_json_stdout_is_clean(monkeypatch):
    # progress goes to stderr; --json stdout must be parseable JSON
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "create", "new1", "--wait", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)              # stdout is pure JSON
    assert data[0]["name"] == "new1"
    assert "creating container" in res.stderr    # progress on stderr, not stdout


def test_agent_create_error_exit_code(monkeypatch):
    _patch_client(monkeypatch, raise_error=ControlError("provision failed", exit_code=1))
    res = runner.invoke(cli_app.app, ["agent", "create", "new1"])
    assert res.exit_code == 1


def test_agent_rm_error_maps_exit_code(monkeypatch):
    _patch_client(monkeypatch, raise_error=ControlError("boom", exit_code=1))
    res = runner.invoke(cli_app.app, ["agent", "rm", "a1"])
    assert res.exit_code == 1


def test_agent_config_no_options_is_usage_error(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "config", "a1"])
    assert res.exit_code == 2


def test_agent_config_soul_conflict_usage_error(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "config", "a1", "--soul", "x", "--soul-file", "/p"])
    assert res.exit_code == 2


def test_agent_config_set(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "config", "a1", "--add-skill", "s1"])
    assert res.exit_code == 0
    assert "applied" in res.stdout


def test_agent_chat_once(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "chat", "a1", "hello"])
    assert res.exit_code == 0
    assert "hello" in res.stdout


def test_gateway_status_down(monkeypatch):
    _patch_gateway(monkeypatch, GatewayStatus(running=False, version="0.1.0"))
    res = runner.invoke(cli_app.app, ["gateway", "status"])
    assert res.exit_code == 0
    assert "NOT running" in res.stdout


def test_gateway_status_json(monkeypatch):
    _patch_gateway(monkeypatch, GatewayStatus(running=True, pid=7, version="0.1.0"))
    res = runner.invoke(cli_app.app, ["gateway", "status", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["pid"] == 7


# ================= U8: doctor + gateway config --runtime =================
def test_doctor_ok(monkeypatch):
    _patch_client(monkeypatch, up=True)
    from caduceus.config import doctor as doc
    rep = doc.DoctorReport([doc.Check("docker", ok=True, detail="server 27.0")])
    monkeypatch.setattr("caduceus.config.doctor.run_doctor", lambda **kw: rep)
    res = runner.invoke(cli_app.app, ["doctor"])
    assert res.exit_code == 0
    assert "docker" in res.stdout


def test_doctor_problem_exit_code(monkeypatch):
    _patch_client(monkeypatch, up=False)
    from caduceus.config import doctor as doc
    rep = doc.DoctorReport([doc.Check("container runtime (runsc)", ok=False,
                                      detail="missing", hint="install gVisor")])
    monkeypatch.setattr("caduceus.config.doctor.run_doctor", lambda **kw: rep)
    res = runner.invoke(cli_app.app, ["doctor"])
    assert res.exit_code == 1


def test_gateway_config_set_runtime(monkeypatch):
    fake = _patch_client(monkeypatch, up=True)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--runtime", "runsc"])
    assert res.exit_code == 0
    assert fake.set_gateway_calls and fake.set_gateway_calls[0].container_runtime == "runsc"


def test_gateway_config_bad_runtime(monkeypatch):
    _patch_client(monkeypatch, up=True)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--runtime", "bogus"])
    assert res.exit_code == 2  # usage/validation error
