# U4 CLI / Daemon / Config — Logical Components

Logical (technology-agnostic) component view realizing the NFR patterns. U4 is the
composition root; lower-unit collaborators are constructed here and injected as interfaces.

## Components (in `caduceus/`)

### cli/ — `caduceus.cli`
- **Role**: typer app + command handlers (`agent …`, `gateway …`) + output rendering.
- **Patterns**: thin adapter; dual renderer; total exit-code mapping.
- **Depends on**: `ControlAPIClient` (only). No direct service imports → CLI is testable with a fake client (typer `CliRunner`).

### ControlAPIClient — `caduceus.cli.client`
- **Role**: loopback HTTP client to the Control API; unary calls + SSE consumption (`chat`/`logs`); `is_daemon_up`.
- **Patterns**: adapter; SSE pass-through. **Depends on**: `httpx`.

### daemon/ — `caduceus.daemon`
- **GatewayService** (C3): lifecycle `start/stop/status`, `build_app()`, signal handling, daemonize, **composition-root wiring** (constructs U2 `AgentService`, U3 `ChatService`/`Supervisor`, U1 `AIGatewayService`; injects callables).
- **InstanceLock**: pid/lock acquire/reclaim/release.
- **ControlAPI** (C4): FastAPI routes → services; error-to-response boundary; chat/logs as SSE.
- **Patterns**: composition root + DI; single-instance lock; graceful shutdown; bulkhead (split listeners); error boundary.

### config/ — `caduceus.config`
- **ConfigService** (C8): `get_config`/`set_config`; remote → `ReadOnlyError` (FR-E2).
- **ConfigEditor** (C16): `read`/`apply` — pure `apply_change` reducer at the core; sandbox I/O via injected U2 `Provisioner`; `ReloadStrategy` resolution; verify-after-write.
- **Patterns**: pure-function core; strategy (CHANGE_KIND_STRATEGY); verify-after-write.
- **Depends on (injected)**: U2 `Provisioner`/`Registry`; (later) U3 restart path for `restart_serve` kinds.

### common/ — extend existing
- **Settings** (`common/settings.py`): add the TOML file layer (`from_env_and_file`) preserving env > file > default; `config.toml` writer (perms 600).
- **Logging** (`common/logging.py`): already redacting; reused for the daemon log file.
- **DTOs** (`common/models.py` or `daemon/dto.py`): `CreateSpec`/`RegisterSpec`/`AgentView`/`GatewayStatus`/`ConfigSnapshot`/`ConfigChange`/`ConfigResult` (dataclasses + `to_dict`/`from_dict`).

## Component interaction (text)
```
caduceus (typer CLI)  ── ControlAPIClient ──http/SSE──> Control API (127.0.0.1:9700)
                                                           │   (GatewayService.build_app)
  Control API routes ──> AgentService (U2) / ChatService (U3) / ConfigService (U4)
  GatewayService.start ──constructs+injects──> Registry, AgentService, ChatService,
                                               Supervisor (U3), AIGatewayService (U1)
  AIGatewayService mounted on second listener (bridge:9701), token_lookup=Registry.token_lookup
  ConfigService ──> ConfigEditor ──apply_change(pure)──> Provisioner (U2, sandbox I/O)
```

## Injected interfaces (no concrete infra in unit tests)
| Dependency | Source | Test double |
|---|---|---|
| `ControlAPIClient` | U4 | fake client (CLI tests via CliRunner) |
| `AgentService`/`ChatService`/`ConfigService` | U2/U3/U4 | fakes / in-process ASGI client |
| `Provisioner` | U2 | `FakeProvisioner` (config read-back/apply) |
| `Transport`/health/restart | U3 | injected callables / FakeTransport |
| clock / fork / lock | stdlib | monkeypatched in tests |

## Realized properties (link to PBT-01)
- DTO round-trip → **PBT-U4-1**. Pure reducer idempotent/order-independent → **PBT-U4-2**.
- No-secret projection → **PBT-U4-3**. Remote read-only → **PBT-U4-4**.
- Reload-strategy totality + seam → **PBT-U4-5**. Exit-code totality → **PBT-U4-6**.

## Deferred to Infrastructure Design / Build & Test
- Exact daemonization details on WSL2, hermes config-reload mechanism + in-sandbox config paths, and the real end-to-end CLI→daemon→agent path (AC-1..AC-7) — validated in Build & Test.
