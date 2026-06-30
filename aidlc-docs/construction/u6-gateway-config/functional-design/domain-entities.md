# U6 — Domain Entities (Functional Design, light)

This unit adds **no new persistent entity**. It operates on the existing `Settings`
(`caduceus/common/settings.py`) and its on-disk form `~/.caduceus/config.toml`. Two small
DTOs frame the view/edit operation.

## GatewayConfigView (read projection)
A secret-free snapshot of the gateway's effective upstream config.

| Field | Type | Notes |
|---|---|---|
| `upstream_base_url` | `str \| None` | Effective value (`env > config.toml`), or live daemon value when running. |
| `default_model` | `str \| None` | Effective value. |
| `upstream_configured` | `bool` | `True` iff both required fields are set (mirrors `Settings.missing_required`). |
| `source` | `str` | `"live"` (read from running daemon) or `"file"` (daemon down → from config.toml/env). |
| `env_override` | `list[str]` | Names of keys currently forced by env vars (so the UI can warn a persisted change is shadowed). |

- **Excludes** `upstream_auth` and all other settings (out of scope, Q3=A). Never emits secrets (BR-GC8).

## GatewayConfigChange (edit intent)
| Field | Type | Notes |
|---|---|---|
| `upstream_base_url` | `str \| None` | New value, or `None` = leave unchanged. |
| `default_model` | `str \| None` | New value, or `None` = leave unchanged. |

- **Invariant**: at least one field non-`None` (BR-GC1).
- Whitespace is trimmed; empty string after trim is treated as invalid, not as "clear".

## Relationship to existing types
- `Settings` — the live, in-memory config object held by the daemon (`Services.settings`) and
  read live by `UpstreamClient` and `routing.build_route`.
- `config.toml` — durable form, written atomically (BR-GC4); already read by
  `Settings.from_env_and_file`.

Both DTOs live in `caduceus/common/dto.py` alongside the existing `AgentView` / `ConfigChange`,
with `to_dict` / `from_dict` for the Control-API JSON boundary.
