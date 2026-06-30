# U4 CLI / Daemon / Config — Domain Entities

Technology-agnostic domain model for U4 (the composition root). Reuses `AgentRecord`,
`AgentKind`, `Lifecycle`, `HealthStatus`, `HealthLevel` from `common/models.py` and
`Settings`/`Timeouts` from `common/settings.py`. U4 adds the **API DTOs**, the **config
edit** model, and the **CLI command surface**.

## Request specs (CLI → Control API)
### CreateSpec
| Field | Type | Notes |
|---|---|---|
| `name` | `str` | agent name (validated by U2) |
| `model` | `str?` | per-agent model alias override (default `"default"`) |
| `upstream_url` | `str?` | per-agent upstream override (designed-for; v2) |
| `image` | `str?` | hermes image tag override |

### RegisterSpec
| Field | Type | Notes |
|---|---|---|
| `name` | `str` | agent name |
| `endpoint` | `str` | remote hermes endpoint URL (required) |
| `auth` | `str?` | optional bearer for the remote endpoint |

## Projections (Control API → CLI)
### AgentView  *(projection of `AgentRecord` + `HealthStatus`; never includes secrets)*
| Field | Type |
|---|---|
| `name` | `str` |
| `kind` | `"local"\|"remote"` |
| `lifecycle` | `creating\|running\|stopped\|failed\|registered` |
| `health` | `healthy\|degraded\|unhealthy\|unknown` |
| `endpoint` | `str?` |
| `model_alias` | `str` |
| `has_session` | `bool`  *(session_id present — id itself not exposed)* |
| `created_at` | `str?` |

> **Secret rule**: `token` and `serve_auth` are NEVER projected into `AgentView`/JSON output.

### GatewayStatus
| Field | Type |
|---|---|
| `pid` | `int?` |
| `uptime_s` | `float?` |
| `control_listener` | `str`  (e.g. `127.0.0.1:9700`) |
| `aigateway_listener` | `str`  (e.g. `172.17.0.1:9701`) |
| `upstream` | `healthy\|degraded\|unhealthy\|unknown` |
| `agent_count` | `int` |
| `version` | `str` |
| `running` | `bool` |

## Config edit model (FR-E1..E3)
### ConfigSnapshot  *(current agent config as read from the sandbox)*
| Field | Type |
|---|---|
| `skills` | `list[str]` |
| `tools` | `{enabled: list[str], disabled: list[str]}` |
| `soul` | `str` |
| `core` | `dict[str, str]` |

### ConfigChange  *(requested edit; all fields optional/cumulative)*
| Field | Type | CLI |
|---|---|---|
| `add_skills` | `list[str]` | `--add-skill` |
| `remove_skills` | `list[str]` | `--remove-skill` |
| `enable_tools` | `list[str]` | `--enable-tool` |
| `disable_tools` | `list[str]` | `--disable-tool` |
| `soul` | `str?` | `--soul "<text>"` (inline, Q5=B) |
| `soul_file` | `str?` | `--soul-file <path>` (file contents) |
| `set_core` | `dict[str, str]` | `--set key=value` |

### ReloadStrategy (enum) — Q2 seam
| Value | v1 use |
|---|---|
| `hot_reload` | **default for every change kind** — apply files + signal hermes to reload, no serve restart |
| `restart_serve` | reserved — flip specific change kinds here later to force a `hermes serve` restart (reuses U3/U2 restart path) |

`CHANGE_KIND_STRATEGY: dict[ChangeKind, ReloadStrategy]` maps `{skills, tools, soul, core}` → strategy.
v1 maps **all kinds → `hot_reload`**; the map is the single seam to change later (BR-E5).

### ConfigResult
| Field | Type | Notes |
|---|---|---|
| `applied` | `list[str]` | human summary of applied edits |
| `strategy` | `hot_reload\|restart_serve` | the effective strategy used (max over affected kinds) |
| `reloaded` | `bool` | hermes reload/restart performed |
| `verified` | `bool` | read-back confirmed intended values (Q4) |
| `health` | `HealthLevel` | post-apply health |
| `detail` | `str` | message / error detail |

## CLI command surface (C1)
| Command | Handler intent |
|---|---|
| `agent create <name> [--model] [--upstream-url] [--image]` | CreateSpec → POST /agents |
| `agent register <name> --endpoint <url> [--auth]` | RegisterSpec → POST /agents/register |
| `agent ls [--json] [--deep]` | GET /agents → render AgentView table/JSON |
| `agent chat <name> [query]` | interactive streaming chat (SSE); query omitted → REPL |
| `agent config <name> [--get] [--json] [--add-skill ...] [--remove-skill ...] [--enable-tool ...] [--disable-tool ...] [--soul <text>] [--soul-file <path>] [--set k=v ...]` | get → ConfigSnapshot; else ConfigChange → PUT /config |
| `agent logs <name> [-f/--follow]` | GET /agents/{name}/logs (SSE) |
| `agent stop\|start <name>` | POST /agents/{name}/stop\|start |
| `agent rm <name> [--force]` | DELETE /agents/{name} |
| `gateway start [-d/--daemon] [--foreground]` | start daemon (foreground default; `-d` daemonize) |
| `gateway stop` | stop daemon |
| `gateway status [--json]` | GatewayStatus |

## Daemon runtime entities (in-memory)
- **InstanceLock** — single-instance guard: `~/.caduceus/caduceus.pid` + lock; holds `pid`, `started_at`.
- **GatewayApps** — `(control_app, aigateway_app)` ASGI apps built by `build_app()`.
- **Wiring** — the composition root constructs U2 `AgentService`, U3 `ChatService`/`Supervisor` and injects callables (`list_agents`, `health_check`, `restart`, `mark_failed`) — see business-logic-model.
