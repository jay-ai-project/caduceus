"""Example-based tests for routing (BR-2). PBT-10 anchors for the model rule."""

from caduceus.aigateway.routing import build_route, resolve_model
from caduceus.common.settings import Settings

D = "stub-model"  # neutral test default model (no personal value baked in)


def test_sentinel_resolves_to_default():
    assert resolve_model("default", D) == D
    assert resolve_model("DEFAULT", D) == D
    assert resolve_model("  default ", D) == D
    assert resolve_model(None, D) == D


def test_explicit_model_passes_through():
    assert resolve_model("foo/bar", D) == "foo/bar"
    assert resolve_model("llamacpp/other", D) == "llamacpp/other"


def test_build_route_rewrite_flag():
    s = Settings(upstream_base_url="http://stub/v1", default_model=D)
    r1 = build_route("default", s)
    assert r1.rewrite_model is True
    assert r1.effective_model == D
    assert r1.base_url == "http://stub/v1"

    r2 = build_route("foo/bar", s)
    assert r2.rewrite_model is False
    assert r2.effective_model == "foo/bar"
