"""U6 — gateway config: validation, atomic key-preserving store, service, DTOs."""

from __future__ import annotations

import pytest

from caduceus.common.dto import GatewayConfigChange, GatewayConfigView
from caduceus.common.settings import Settings
from caduceus.config import gateway_config as gwc


# ---- validation (BR-GC1/GC2/GC3) ----
@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "https://api.example.com/v1", "http://h"])
def test_validate_url_ok(url):
    gwc.validate_url(url)  # no raise


@pytest.mark.parametrize("url", ["", "   ", "ftp://h", "notaurl", "http://", "://nohost"])
def test_validate_url_bad(url):
    with pytest.raises(ValueError):
        gwc.validate_url(url)


def test_validate_change_empty_raises():
    with pytest.raises(ValueError):
        gwc.validate_change(GatewayConfigChange())


def test_validate_change_bad_model():
    with pytest.raises(ValueError):
        gwc.validate_change(GatewayConfigChange(default_model="   "))


# ---- container runtime (U8, BR-R3) ----
@pytest.mark.parametrize("rt", ["runc", "runsc"])
def test_validate_runtime_ok(rt):
    gwc.validate_runtime(rt)  # no raise


@pytest.mark.parametrize("rt", ["", "  ", "docker", "gvisor", "RunC"])
def test_validate_runtime_bad(rt):
    with pytest.raises(ValueError):
        gwc.validate_runtime(rt)


def test_validate_change_bad_runtime():
    with pytest.raises(ValueError):
        gwc.validate_change(GatewayConfigChange(container_runtime="nope"))


def test_service_apply_runtime_hot_applies(tmp_path):
    p = tmp_path / "config.toml"
    settings = Settings(upstream_base_url="http://h/v1", default_model="m")
    svc = gwc.GatewayConfigService(settings, config_path=p)
    view = svc.apply(GatewayConfigChange(container_runtime="runsc"))
    assert settings.container_runtime == "runsc"           # live object mutated
    assert gwc.load_toml(p)["container_runtime"] == "runsc"  # persisted
    assert view.container_runtime == "runsc"


def test_change_trims_and_is_empty():
    c = GatewayConfigChange(upstream_base_url="  http://h  ", default_model=None)
    assert c.upstream_base_url == "http://h"
    assert not c.is_empty()
    assert GatewayConfigChange().is_empty()


# ---- DTO round-trip ----
def test_view_dto_round_trip():
    v = GatewayConfigView(upstream_base_url="http://h", default_model="m",
                          upstream_configured=True, source="live", env_override=["default_model"])
    assert GatewayConfigView.from_dict(v.to_dict()) == v


# ---- atomic, key-preserving store (BR-GC4) ----
def test_apply_to_toml_preserves_other_keys(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'upstream_base_url = "http://old/v1"\n'
        'default_model = "old-model"\n'
        'control_bind = "127.0.0.1:9700"\n'
        'aigateway_bind = "0.0.0.0:9701"\n'
        "\n[timeouts]\nconnect = 10\nread = 120\n",
        encoding="utf-8",
    )
    gwc.apply_to_toml(p, GatewayConfigChange(upstream_base_url="http://new/v1"))

    data = gwc.load_toml(p)
    assert data["upstream_base_url"] == "http://new/v1"
    assert data["default_model"] == "old-model"          # untouched
    assert data["control_bind"] == "127.0.0.1:9700"      # preserved
    assert data["timeouts"] == {"connect": 10, "read": 120}  # nested table preserved


def test_apply_to_toml_creates_file_when_absent(tmp_path):
    p = tmp_path / "sub" / "config.toml"
    gwc.apply_to_toml(p, GatewayConfigChange(upstream_base_url="http://h/v1", default_model="m"))
    data = gwc.load_toml(p)
    assert data == {"upstream_base_url": "http://h/v1", "default_model": "m"}
    # Settings can load the file we wrote.
    s = Settings.from_env_and_file(p)
    assert s.upstream_base_url == "http://h/v1" and s.default_model == "m"


def test_write_is_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "config.toml"
    gwc.apply_to_toml(p, GatewayConfigChange(default_model="m"))
    leftovers = [f.name for f in tmp_path.iterdir() if ".tmp." in f.name]
    assert leftovers == []


# ---- service: persist + hot-apply (BR-GC5/GC9) ----
def test_service_apply_persists_and_hot_applies(tmp_path):
    p = tmp_path / "config.toml"
    settings = Settings(upstream_base_url="http://old/v1", default_model="old")
    svc = gwc.GatewayConfigService(settings, config_path=p)

    view = svc.apply(GatewayConfigChange(upstream_base_url="http://new/v1", default_model="new"))

    assert settings.upstream_base_url == "http://new/v1"   # live object mutated
    assert settings.default_model == "new"
    assert gwc.load_toml(p)["upstream_base_url"] == "http://new/v1"  # persisted
    assert view.source == "live" and view.upstream_configured


def test_service_apply_invalid_does_not_write(tmp_path):
    p = tmp_path / "config.toml"
    settings = Settings(upstream_base_url="http://old/v1", default_model="old")
    svc = gwc.GatewayConfigService(settings, config_path=p)
    with pytest.raises(ValueError):
        svc.apply(GatewayConfigChange(upstream_base_url="bad"))
    assert not p.exists()                       # nothing persisted
    assert settings.upstream_base_url == "http://old/v1"  # unchanged


def test_view_reports_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CADUCEUS_DEFAULT_MODEL", "envm")
    settings = Settings(upstream_base_url="http://h", default_model="envm")
    view = gwc.view_from_settings(settings, source="file")
    assert "default_model" in view.env_override
    assert "upstream_base_url" not in view.env_override
