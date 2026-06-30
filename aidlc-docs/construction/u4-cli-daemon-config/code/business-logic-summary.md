# U4 CLI / Daemon / Config — Business Logic Summary (code)

Generated application code (workspace root). U4 is the composition root that turns
U1+U2+U3 into the single `caduceus` deployable.

## Modules
| File | Responsibility | Rules |
|---|---|---|
| `common/dto.py` | API DTOs (`CreateSpec`/`RegisterSpec`/`AgentView`/`GatewayStatus`/`ConfigSnapshot`/`ConfigChange`/`ConfigResult`); **pure** `apply_change` reducer (idempotent, disable-wins tie-break) + `snapshot_satisfies`; `ReloadStrategy`/`CHANGE_KIND_STRATEGY`/`resolve_strategy` (Q2 seam); `AgentView.from_record` secret-stripped. | BR-E3/E5, BR-O3 |
| `common/settings.py` (extended) | `from_env_and_file` (env > `config.toml` > default via `tomllib`); `write_config_toml` (perms 600). | BR-G6/Q3 |
| `daemon/lock.py` | `InstanceLock` — pid file + liveness; stale reclaim; context manager. | BR-G3 |
| `config/editor.py` | `ConfigEditor.read/apply` — reduce → write → reload (strategy) → **read-back + health verify** → `ConfigResult`; soul-conflict guard; `ReadOnlyError`. I/O injected. | FR-E1/E3, Q2/Q4, BR-E2/E4/E6 |
| `config/service.py` | `ConfigService.get/set` — local only; remote → `ReadOnlyError`; resolves `--soul-file` (edge I/O) before the pure reduce. | FR-E1/E2, BR-E1 |
| `daemon/wiring.py` | **Composition root** `build_services(settings)` — constructs Registry, SbxProvisioner, ImageBuilder, HealthChecker (with U3 `transport_healthy` probe), AgentService (U2), ChatService + Supervisor (U3, injected `restart`/`mark_failed`/`list_agents`), AIGatewayService (U1, `token_lookup`=Registry). | BR-W1/W2 |
| `daemon/control_api.py` | `build_control_app(services)` — FastAPI routes → services; chat/logs SSE; `AgentView` projection; error→JSON boundary (`ReadOnlyError`→409). | FR-G3, C4 |
| `daemon/gateway.py` | `GatewayService.start/stop/status` + `bootstrap_config` (Q3) + `build_apps`; `_daemonize`/`_serve` isolated (Build & Test). | FR-G1..G4 |
| `cli/client.py` | `ControlAPIClient` (httpx unary + SSE), `is_daemon_up`, `ControlError(exit_code)`. | C2 |
| `cli/render.py` | human/json renderers + `EXIT_OK/RUNTIME/USAGE`. | Q6/BR-O1/O2 |
| `cli/app.py` | typer app + handlers (`agent …`, `gateway …`); interactive `chat`; daemon-down guidance; usage/runtime exit codes. | FR-G2, C1, Q6 |
| `__main__.py` | `python -m caduceus`. | — |

## Key flows
- **Composition (BR-W1)**: `wiring.build_services` is the only place units are concretely connected — `restart(rec)` = Provisioner `start_serve` re-publish + Registry upsert (BR-W2); `transport_healthy` opens a `Transport` and calls `health()` (no LLM).
- **Config apply (Q2/Q4)**: pure reduce on the snapshot → write → `resolve_strategy` (v1 `hot_reload`) → reload → read-back `snapshot_satisfies` + shallow health → `ConfigResult`.
- **Daemon start (Q1/Q3)**: bootstrap (prompt+persist or `ConfigError`) → lock → build apps → (`-d` daemonize) → serve both listeners → Supervisor.start.

## Deferred to Build & Test (flagged in code)
- `gateway._serve` (uvicorn), `gateway._daemonize` (fork/setsid), real `ControlAPIClient` over TCP, and the sandbox config codec in `wiring._make_read/write/reload` (hermes reload mechanism + config paths). Same convention as U2 `SbxProvisioner` / U3 `ServeTransport`.
