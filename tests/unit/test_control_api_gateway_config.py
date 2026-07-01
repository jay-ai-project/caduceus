"""U6 — Control API `/gateway/config` GET/POST over fake services (in-process ASGI)."""

from __future__ import annotations

import httpx

from caduceus.common.settings import Settings
from caduceus.config.gateway_config import GatewayConfigService
from caduceus.daemon.control_api import build_control_app

from tests.fakes import build_fake_services


def _client(services):
    app = build_control_app(services)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ctl")


def _services_with_config(tmp_path, **settings_kw):
    services = build_fake_services()
    settings = Settings(**settings_kw)
    services.gateway_config_service = GatewayConfigService(settings, tmp_path / "config.toml")
    return services, settings


async def test_get_gateway_config(tmp_path):
    services, _ = _services_with_config(tmp_path, upstream_base_url="http://up/v1", default_model="m")
    async with _client(services) as c:
        body = (await c.get("/gateway/config")).json()
    assert body == {
        "upstream_base_url": "http://up/v1", "default_model": "m",
        "container_runtime": "runc",
        "upstream_configured": True, "source": "live", "env_override": [],
    }


async def test_post_gateway_config_applies_and_persists(tmp_path):
    services, settings = _services_with_config(tmp_path, upstream_base_url="http://old/v1", default_model="old")
    async with _client(services) as c:
        resp = await c.post("/gateway/config", json={"upstream_base_url": "http://new/v1"})
    assert resp.status_code == 200
    assert resp.json()["upstream_base_url"] == "http://new/v1"
    assert settings.upstream_base_url == "http://new/v1"          # hot-applied
    assert (tmp_path / "config.toml").exists()                    # persisted


async def test_post_gateway_config_validation_400(tmp_path):
    services, settings = _services_with_config(tmp_path, upstream_base_url="http://old/v1", default_model="old")
    async with _client(services) as c:
        resp = await c.post("/gateway/config", json={"upstream_base_url": "notaurl"})
    assert resp.status_code == 400
    assert settings.upstream_base_url == "http://old/v1"          # unchanged


async def test_post_gateway_config_empty_400(tmp_path):
    services, _ = _services_with_config(tmp_path, upstream_base_url="http://old/v1", default_model="old")
    async with _client(services) as c:
        resp = await c.post("/gateway/config", json={})
    assert resp.status_code == 400
