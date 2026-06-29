"""Example-based tests for /v1/models augmentation (BR-8)."""

from caduceus.aigateway.models_augment import augment_models


def test_injects_default_alias():
    out = augment_models({"object": "list", "data": [{"id": "m1"}]})
    ids = [m["id"] for m in out["data"]]
    assert "default" in ids
    assert "m1" in ids


def test_no_duplicate_default():
    out = augment_models({"object": "list", "data": [{"id": "default"}, {"id": "m1"}]})
    ids = [m["id"] for m in out["data"]]
    assert ids.count("default") == 1


def test_upstream_unavailable_returns_default_only():
    out = augment_models(None)
    assert out["data"] == [{"id": "default", "object": "model", "owned_by": "caduceus"}]
