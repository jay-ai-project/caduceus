"""PURE routing logic: model resolution + route building.

Business rule BR-2 (model resolution):
- model absent or == "default" (case-insensitive) -> configured default model
- otherwise -> the requested model, unchanged (pass-through)
"""

from __future__ import annotations

from dataclasses import dataclass

from caduceus.common.settings import SENTINEL_MODEL, Settings


def is_sentinel(model: str | None) -> bool:
    return model is None or model.strip().lower() == SENTINEL_MODEL


def resolve_model(model: str | None, default_model: str) -> str:
    """Apply BR-2. Pure and total."""
    if is_sentinel(model):
        return default_model
    return model


@dataclass(frozen=True)
class Route:
    base_url: str
    effective_model: str
    rewrite_model: bool


def build_route(model: str | None, settings: Settings, agent_id: str | None = None) -> Route:
    """Resolve where/how to forward a request.

    v1: the upstream is always ``settings.upstream_base_url`` regardless of
    ``agent_id``. The ``agent_id`` parameter is the seam for v2 per-agent
    override (model/url keyed by agent).
    """
    rewrite = is_sentinel(model)
    effective = settings.default_model if rewrite else model
    return Route(
        base_url=settings.upstream_base_url,
        effective_model=effective,
        rewrite_model=rewrite,
    )
