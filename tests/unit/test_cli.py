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


def test_agent_create(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["agent", "create", "new1"])
    assert res.exit_code == 0
    assert "new1" in res.stdout


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
