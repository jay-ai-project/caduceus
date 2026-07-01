"""U6 — gateway upstream config: validate, atomically persist, and hot-apply.

`upstream_base_url` / `default_model` are the only editable keys (Q3). The store
does a **key-preserving** read-modify-write of `config.toml` (atomic temp + replace,
perms 600 — BR-GC4). When the daemon is running, `GatewayConfigService` mutates the
**live** `Settings` object in place so `UpstreamClient._url()` and
`routing.build_route()` pick up the change without a restart (BR-GC5).

Validation is light (Q5/BR-GC2/GC3): non-empty + URL shape, no network calls.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from caduceus.common.dto import GatewayConfigChange, GatewayConfigView
from caduceus.common.settings import Settings

#: The only keys this command edits, and the env vars that shadow them (BR-GC7).
ENV_KEYS = {
    "upstream_base_url": "CADUCEUS_UPSTREAM_BASE_URL",
    "default_model": "CADUCEUS_DEFAULT_MODEL",
    "container_runtime": "CADUCEUS_CONTAINER_RUNTIME",
}

#: Allowed container runtimes (U8, BR-R3).
VALID_RUNTIMES = ("runc", "runsc")


# ---- validation (light; BR-GC2/GC3/R3) ----------------------------
def validate_url(url: str | None) -> None:
    if not url or not url.strip():
        raise ValueError("upstream_base_url must not be empty")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("upstream_base_url must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError("upstream_base_url must include a host")


def validate_model(model: str | None) -> None:
    if not model or not model.strip():
        raise ValueError("default_model must not be empty")


def validate_runtime(runtime: str | None) -> None:
    if not runtime or runtime.strip() not in VALID_RUNTIMES:
        raise ValueError(f"container_runtime must be one of {', '.join(VALID_RUNTIMES)}")


def validate_change(change: GatewayConfigChange) -> None:
    if change.is_empty():
        raise ValueError("no changes requested (provide --upstream-url, --model, and/or --runtime)")
    if change.upstream_base_url is not None:
        validate_url(change.upstream_base_url)
    if change.default_model is not None:
        validate_model(change.default_model)
    if change.container_runtime is not None:
        validate_runtime(change.container_runtime)


# ---- atomic, key-preserving config.toml store (BR-GC4) ------------
def load_toml(path: "str | os.PathLike") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_toml(data: dict) -> str:
    """Minimal TOML serializer covering config.toml's shape: top-level scalars +
    one level of nested tables (e.g. ``[timeouts]``). Preserves unrelated keys."""
    scalars = [(k, v) for k, v in data.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in data.items() if isinstance(v, dict)]
    lines = [f"{k} = {_fmt(v)}" for k, v in scalars]
    for name, tbl in tables:
        lines.append(f"\n[{name}]")
        lines.extend(f"{k} = {_fmt(v)}" for k, v in tbl.items())
    return "\n".join(lines) + "\n"


def atomic_write_toml(path: "str | os.PathLike", data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    tmp.write_text(dump_toml(data), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)  # atomic within the same directory


def apply_to_toml(path: "str | os.PathLike", change: GatewayConfigChange) -> None:
    """Persist `change` into config.toml, leaving every other key intact."""
    data = load_toml(path)
    if change.upstream_base_url is not None:
        data["upstream_base_url"] = change.upstream_base_url
    if change.default_model is not None:
        data["default_model"] = change.default_model
    if change.container_runtime is not None:
        data["container_runtime"] = change.container_runtime
    atomic_write_toml(path, data)


# ---- views --------------------------------------------------------
def env_override_keys() -> list[str]:
    return [key for key, env in ENV_KEYS.items() if os.getenv(env)]


def view_from_settings(settings: Settings, source: str) -> GatewayConfigView:
    return GatewayConfigView(
        upstream_base_url=settings.upstream_base_url,
        default_model=settings.default_model,
        container_runtime=settings.container_runtime,
        upstream_configured=not settings.missing_required(),
        source=source,
        env_override=env_override_keys(),
    )


# ---- daemon-side service (view + persist + hot-apply) -------------
class GatewayConfigService:
    """Holds the live `Settings` + config.toml path. `apply` persists durably
    first, then hot-applies in memory (BR-GC9)."""

    def __init__(self, settings: Settings, config_path: "str | os.PathLike"):
        self.settings = settings
        self.config_path = Path(config_path)

    def view(self) -> GatewayConfigView:
        return view_from_settings(self.settings, source="live")

    def apply(self, change: GatewayConfigChange) -> GatewayConfigView:
        validate_change(change)                      # ValueError -> HTTP 400
        apply_to_toml(self.config_path, change)      # durable first (BR-GC9)
        if change.upstream_base_url is not None:     # then hot-apply (BR-GC5)
            self.settings.upstream_base_url = change.upstream_base_url
        if change.default_model is not None:
            self.settings.default_model = change.default_model
        if change.container_runtime is not None:
            # Applies to newly-spawned containers (existing keep their runtime; BR-R3).
            self.settings.container_runtime = change.container_runtime
        return self.view()
