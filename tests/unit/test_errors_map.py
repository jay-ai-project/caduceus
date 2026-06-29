"""Example-based tests for error mapping (BR-7)."""

import httpx

from caduceus.aigateway.errors_map import map_error
from caduceus.common.errors import ProxyError


def test_timeout_maps_to_504():
    e = map_error(httpx.ReadTimeout("slow"))
    assert e.http_status == 504
    assert e.type == "timeout_error"


def test_connect_error_maps_to_502():
    e = map_error(httpx.ConnectError("refused"))
    assert e.http_status == 502
    assert e.type == "upstream_error"


def test_proxy_error_passthrough():
    original = ProxyError(401, "authentication_error", "nope")
    assert map_error(original) is original


def test_unexpected_maps_to_500():
    e = map_error(ValueError("boom"))
    assert e.http_status == 500
    assert e.to_openai()["error"]["type"] == "upstream_error"
