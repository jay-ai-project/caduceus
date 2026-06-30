# U4 CLI / Daemon / Config — Business Logic Model

Technology-agnostic flows for the composition root: daemon lifecycle, Control API ↔
services, CLI ↔ daemon, and config editing. Wires U1 (AI-Gateway), U2 (agents), U3
(transport/chat/supervisor).

Decisions in force: **Q1** foreground default + `-d` daemonize · **Q2** hot-reload default
with a per-change-kind `ReloadStrategy` seam · **Q3** interactive config bootstrap +
`config.toml` · **Q4** apply→read-back→health verify · **Q5** `--soul`/`--soul-file` · **Q6**
human default + `--json` + non-zero exit codes.

---

## L1. Daemon / GatewayService lifecycle (FR-G1..G4)

### start(foreground: bool=True, daemonize: bool=False)
1. **Config bootstrap (Q3)**: `Settings.from_env()` (env > file `~/.caduceus/config.toml` > default). If `missing_required()`:
   - foreground + interactive TTY → prompt for `upstream_base_url`/`default_model`, write to `config.toml`.
   - else → raise `ConfigError` with guidance (non-interactive/daemonized). 
2. **Single-instance lock**: acquire `~/.caduceus/caduceus.pid` (+ lock). If held by a live pid → error "already running". 
3. **Daemonize (Q1)**: if `-d` → detach a child (new session, stdout/stderr → `~/.caduceus/logs/daemon.log`), parent prints pid and returns; child continues. Default (no `-d`) → run in foreground.
4. **Build apps** `build_app()` → `(control_app, aigateway_app)` (L2).
5. **Wire services** (composition root, L4): construct `Registry`(load), `AgentService` (U2), `ChatService` (U3), `Supervisor` (U3) with injected callables.
6. **Run listeners**: serve `control_app` on `control_bind` (127.0.0.1:9700) and `aigateway_app` on `aigateway_bind` (bridge IP:9701) concurrently.
7. **Supervisor.start()** (U3 background sweep).
8. Install signal handlers (SIGINT/SIGTERM) → `stop()`.

### stop()
- Graceful: `Supervisor.stop()` → stop accepting new requests → drain in-flight → close transports → release lock/pid. Idempotent (no error if already stopped). `gateway stop` (CLI) signals the running pid.

### status() → GatewayStatus
- Read pid/uptime from lock; report both listeners; `upstream` via U1 `check_upstream()`; `agent_count` from Registry; `version`; `running`.

---

## L2. Control API routes → services (C4, FR-G3)

`build_app()` mounts FastAPI routes on the **control** app (loopback only):
| Route | → service |
|---|---|
| `POST /agents` (CreateSpec) | `AgentService.create` → AgentRecord |
| `POST /agents/register` (RegisterSpec) | `AgentService.register` → (AgentRecord, guidance) |
| `GET /agents?deep=` | `AgentService.list` → `AgentView[]` (projection; secrets stripped) |
| `DELETE /agents/{name}?force=` | `AgentService.remove` → 204 |
| `POST /agents/{name}/stop\|start` | `AgentService.stop/start` |
| `POST /agents/{name}/chat` ("{message}") | `ChatService.chat_stream` → **SSE** of `ChatEvent.to_dict()` |
| `GET /agents/{name}/config` | `ConfigService.get_config` → ConfigSnapshot |
| `PUT /agents/{name}/config` (ConfigChange) | `ConfigService.set_config` → ConfigResult |
| `GET /agents/{name}/logs?follow=` | `ConfigService`/Provisioner logs → **SSE** of lines |
| `GET /healthz` | `{ok: true}` |
| `GET /status` | `GatewayService.status` → GatewayStatus |

The **AI-Gateway** app (U1 `AIGatewayService`) is mounted on the separate `aigateway_app`
(split listeners, App Design Q3); `token_lookup` is bound to `Registry.token_lookup`.

Errors map to JSON + HTTP status via the existing `ProxyError.to_openai()` shape; SSE
streams relay terminal `error`/`done` events as data frames.

---

## L3. CLI ↔ daemon (C1/C2, FR-G4, Q6)

- **ControlAPIClient** (C2): HTTP client to `127.0.0.1:9700`; `is_daemon_up(timeout)`; unary calls for CRUD/config/status; **SSE consumption** for `chat` and `logs`.
- **CLI handlers** (typer): build spec → call client → render. Default **human** output (tables/sentences); `--json` → machine JSON. Errors → stderr + exit code: **0** ok, **2** usage error, **1** runtime/upstream failure.
- **`agent chat`**: if `query` given → one turn; else interactive REPL. Streams `token` events to stdout as they arrive; on `error` prints the message + non-zero exit; on `done{cancelled}` (Ctrl-C) exits cleanly. Daemon-down → friendly "run `caduceus gateway start`".
- **Pre-flight**: commands needing the daemon check `is_daemon_up`; `gateway start` is the exception.

---

## L4. Composition root wiring (the U4 raison d'être)

At daemon start, U4 constructs and connects:
- `Registry(state_dir/state.json)`, `.load()`.
- U2 `Provisioner` (`SbxProvisioner`), `ImageBuilder`, `HealthChecker` (with **U3 `transport_healthy` probe** injected), `AgentService(aigateway_url=advertise)`.
- U3 `ChatService(registry, health_check=HealthChecker.check, transport_factory=Transport.for_agent)`.
- U3 `Supervisor(list_agents=registry.list, health_check=HealthChecker.check, restart=<local serve restart>, mark_failed=<set Lifecycle.failed via AgentService/Registry>)`.
- U1 `AIGatewayService(settings, token_lookup=registry.token_lookup, upstream=UpstreamClient)`.

`restart(rec)` = U2 `Provisioner.start_serve` re-launch (+ re-publish port → `registry.upsert`). This is the single place U3's injected callables become concrete.

---

## L5. Config editing (FR-E1..E3, Q2/Q4/Q5)

### ConfigService (C8)
- `get_config(name)`: local → `ConfigEditor.read`; remote → still readable if observable, else clear "remote config is read-only in v1" message (FR-E2).
- `set_config(name, change)`: **local only** → `ConfigEditor.apply`; remote → `ReadOnlyError` (FR-E2).

### ConfigEditor (C16)
`read(name) -> ConfigSnapshot`: read skills/tools/soul/core from inside the sandbox (Provisioner `exec`/`cp`).

`apply(name, change) -> ConfigResult`:
1. Resolve `soul` from `--soul` or `--soul-file` (file wins if both? — reject ambiguous: error if both set).
2. **Reduce** the change onto the current snapshot via the pure `apply_change(snapshot, change)` reducer (order-independent, idempotent — PBT-U4-2).
3. **Write** changed files into the sandbox (Provisioner).
4. **Reload strategy (Q2 seam)**: `strategy = max(CHANGE_KIND_STRATEGY[k] for k in affected_kinds)`. v1 → all `hot_reload`: signal hermes to reload **without** restarting serve. (If a kind is later mapped to `restart_serve`, reuse the U3/U2 restart path.)
5. **Verify (Q4)**: read-back the snapshot; confirm intended values present; run a shallow health check post-reload.
6. Return `ConfigResult{applied, strategy, reloaded, verified, health, detail}`. Any step failure → `verified=False` + actionable detail.

> The exact hermes reload mechanism (reload command vs signal) and config file paths are
> **validated in Build & Test** (same deferral convention as U2/U3 wire details).

---

## L6. Agent logs (FR-L1)
- `agent logs [-f]` → Control API SSE → U2 `Provisioner.logs(sandbox, follow)`; local only (remote logs not available v1, clear message).

---

## Testable Properties (PBT-01)

| ID | Property | Target |
|---|---|---|
| **PBT-U4-1** | All API DTOs (`CreateSpec`/`RegisterSpec`/`AgentView`/`GatewayStatus`/`ConfigSnapshot`/`ConfigChange`/`ConfigResult`) round-trip `from_dict(to_dict(x)) == x`. | DTOs |
| **PBT-U4-2** | `apply_change(snapshot, change)` is **idempotent** (apply twice == once) and **order-independent** for commuting edits; enable+disable of the same tool resolves deterministically. | config reducer (pure) |
| **PBT-U4-3** | `AgentView` projection never contains `token`/`serve_auth` for any `AgentRecord` (no secret leak). | projection |
| **PBT-U4-4** | Remote agents: `set_config`/`stop`/`start` always raise (read-only / unsupported) regardless of input. | ConfigService/AgentService gate |
| **PBT-U4-5** | `ReloadStrategy` resolution is **total** (every change kind maps to a strategy) and defaults to `hot_reload`; if a kind is mapped to `restart_serve`, an affected change yields `restart_serve` (seam works). | CHANGE_KIND_STRATEGY |
| **PBT-U4-6** | CLI exit-code mapping is total: success→0, usage→2, runtime/upstream→1 (no unmapped outcome). | CLI error mapping |

Hypothesis seed logging via the existing `tests/conftest.py` profile (PBT-08).
