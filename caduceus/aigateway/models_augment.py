"""PURE /v1/models augmentation (BR-8): inject the `default` alias, deduped."""

from __future__ import annotations

from caduceus.common.settings import SENTINEL_MODEL


def augment_models(upstream_models: dict | None) -> dict:
    """Return an OpenAI model list that always contains exactly one `default`
    alias, preserving any upstream models.
    """
    data: list[dict] = []
    if upstream_models and isinstance(upstream_models.get("data"), list):
        data = [m for m in upstream_models["data"] if isinstance(m, dict)]

    has_default = any(m.get("id") == SENTINEL_MODEL for m in data)
    if not has_default:
        data = [{"id": SENTINEL_MODEL, "object": "model", "owned_by": "caduceus"}] + data
    return {"object": "list", "data": data}
