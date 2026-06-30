"""U6 — `caduceus gateway config` CLI: view/set, daemon up + offline, exit codes."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from caduceus.cli import app as cli_app
from caduceus.common.dto import GatewayConfigView

from tests.fakes import FakeControlAPIClient

runner = CliRunner()


def _patch_client(monkeypatch, **kw):
    fake = FakeControlAPIClient(**kw)
    monkeypatch.setattr(cli_app, "get_client", lambda: fake)
    return fake


# ---- view ----
def test_view_daemon_up_human(monkeypatch):
    _patch_client(monkeypatch, gateway_config=GatewayConfigView(
        upstream_base_url="http://up/v1", default_model="m", upstream_configured=True, source="live"))
    res = runner.invoke(cli_app.app, ["gateway", "config"])
    assert res.exit_code == 0
    assert "http://up/v1" in res.stdout and "default_model" in res.stdout


def test_view_daemon_up_json(monkeypatch):
    _patch_client(monkeypatch, gateway_config=GatewayConfigView(
        upstream_base_url="http://up/v1", default_model="m", upstream_configured=True, source="live"))
    res = runner.invoke(cli_app.app, ["gateway", "config", "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["upstream_base_url"] == "http://up/v1"


def test_view_daemon_down_reads_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CADUCEUS_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("CADUCEUS_DEFAULT_MODEL", raising=False)
    cfg = tmp_path / ".caduceus" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('upstream_base_url = "http://file/v1"\ndefault_model = "fm"\n', encoding="utf-8")
    _patch_client(monkeypatch, up=False)
    res = runner.invoke(cli_app.app, ["gateway", "config"])
    assert res.exit_code == 0
    assert "http://file/v1" in res.stdout and "source            : file" in res.stdout


# ---- set ----
def test_set_daemon_up_applies_live(monkeypatch):
    fake = _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--upstream-url", "http://new/v1", "--model", "z"])
    assert res.exit_code == 0
    assert "applied live" in res.stdout
    assert fake.set_gateway_calls[0].upstream_base_url == "http://new/v1"
    assert fake.set_gateway_calls[0].default_model == "z"


def test_set_invalid_url_is_usage_error(monkeypatch):
    _patch_client(monkeypatch)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--upstream-url", "notaurl"])
    assert res.exit_code == 2


def test_set_daemon_down_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CADUCEUS_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("CADUCEUS_DEFAULT_MODEL", raising=False)
    _patch_client(monkeypatch, up=False)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--model", "offmodel"])
    assert res.exit_code == 0
    assert "restart" in res.stdout.lower() or "next" in res.stdout.lower()
    import tomllib
    data = tomllib.loads((tmp_path / ".caduceus" / "config.toml").read_text())
    assert data["default_model"] == "offmodel"


def test_set_env_shadow_warns(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CADUCEUS_DEFAULT_MODEL", "envm")
    _patch_client(monkeypatch, up=False)
    res = runner.invoke(cli_app.app, ["gateway", "config", "--model", "newm"])
    assert res.exit_code == 0
    assert "CADUCEUS_DEFAULT_MODEL" in (res.stdout + str(res.stderr))
