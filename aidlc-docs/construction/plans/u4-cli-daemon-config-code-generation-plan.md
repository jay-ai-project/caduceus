# U4 CLI / Daemon / Config — Code Generation Plan

**Unit**: U4 (composition root, final unit). **Workspace root**: `/mnt/f/Workspace/Caduceus`. App code → root; summaries → `aidlc-docs/construction/u4-cli-daemon-config/code/`.

## Unit context
- Implements **FR-G1..G4**, **FR-E1..E3**, **FR-L1**; wires **U1** (`build_aigateway_app`, `UpstreamClient`), **U2** (`AgentService`, `Registry`, `SbxProvisioner`, `ImageBuilder`, `HealthChecker`/`HealthProbes`), **U3** (`ChatService`, `Transport.for_agent`, `Supervisor`).
- **Testable in isolation**: CLI tested via typer `CliRunner` + fake `ControlAPIClient`; Control API via in-process ASGI (`httpx.ASGITransport`) + fake services; ConfigEditor with `FakeProvisioner`. Real uvicorn serving, `-d` fork, and real sbx/hermes go to **Build & Test** (flagged).
- FD decisions: Q1 foreground default + `-d`; Q2 hot-reload default + `CHANGE_KIND_STRATEGY` seam; Q3 config bootstrap + `config.toml`; Q4 read-back verify; Q5 `--soul`/`--soul-file`; Q6 human/`--json` + exit codes.

## Target files (application code)
```
caduceus/common/dto.py            # CreateSpec/RegisterSpec/AgentView/GatewayStatus/ConfigSnapshot/ConfigChange/ConfigResult
                                  #   + pure apply_change reducer + ReloadStrategy/CHANGE_KIND_STRATEGY + resolve_strategy
caduceus/common/settings.py       # EXTEND: from_env_and_file (TOML layer, env>file>default), write_config_toml (perms 600)
caduceus/config/__init__.py
caduceus/config/editor.py         # ConfigEditor.read/apply (reducer + Provisioner I/O + hot-reload + read-back verify); ReadOnlyError
caduceus/config/service.py        # ConfigService.get_config/set_config (local only; remote → ReadOnlyError)
caduceus/daemon/__init__.py
caduceus/daemon/lock.py           # InstanceLock: acquire/reclaim(stale)/release; pid liveness
caduceus/daemon/wiring.py         # build_services(settings, ...) -> Services (Registry, AgentService, ChatService, Supervisor, aigateway app); restart callable + mark_failed
caduceus/daemon/control_api.py    # build_control_app(services) -> FastAPI: agents CRUD, stop/start, chat/logs SSE, config get/put, /status, /healthz
caduceus/daemon/gateway.py        # GatewayService.start/stop/status, build_app, daemonize(-d), signal handlers (serve/fork flagged for Build & Test)
caduceus/cli/__init__.py
caduceus/cli/client.py            # ControlAPIClient (httpx unary + SSE), is_daemon_up
caduceus/cli/render.py            # human/json renderers, EXIT codes, error formatting
caduceus/cli/app.py               # typer app + handlers (agent create/register/ls/chat/config/logs/stop/start/rm; gateway start/stop/status)
caduceus/__main__.py              # python -m caduceus -> cli.app:app
pyproject.toml                    # + typer>=0.12 ; [project.scripts] caduceus = "caduceus.cli.app:app"
tests/fakes.py                    # EXTEND: FakeAgentService, FakeChatService, FakeConfigService, FakeControlAPIClient
tests/unit/test_dto.py            # round-trip, apply_change reducer (idempotent/order-independent), resolve_strategy, no-secret projection
tests/unit/test_settings_file.py  # env>file>default; toml write/read; perms
tests/unit/test_lock.py           # acquire/reclaim/release; stale pid reclaim
tests/unit/test_config_service.py # get/set; remote read-only; editor apply+verify (FakeProvisioner)
tests/unit/test_control_api.py    # ASGI: routes→fakes; chat/logs SSE; /status; error mapping; AgentView secret-stripped
tests/unit/test_cli.py            # CliRunner + FakeControlAPIClient; exit codes; --json; daemon-down message
tests/pbt/test_u4_properties.py   # PBT-U4-1..6
```

## Steps
- [x] **Step 1 — DTOs + pure reducer**: `common/dto.py` — dataclasses (+`to_dict`/`from_dict`); `apply_change(snapshot, change)` pure/idempotent/order-independent; `ReloadStrategy`, `CHANGE_KIND_STRATEGY` (all→hot_reload), `resolve_strategy(kinds)`; `AgentView.from_record(rec, health)` (secret-stripped). [FR-E; PBT-U4-1/2/3/5]
- [x] **Step 2 — DTO tests + PBT**: `tests/unit/test_dto.py`; `tests/pbt/test_u4_properties.py` part 1 (round-trip P-U4-1, reducer P-U4-2, projection P-U4-3, strategy P-U4-5). 
- [x] **Step 3 — Settings file layer**: extend `common/settings.py` — `from_env_and_file(path)` (env>file>default via `tomllib`), `write_config_toml(path, settings)` (perms 600). [Q3]
- [x] **Step 4 — Settings tests**: `tests/unit/test_settings_file.py` (precedence, write/read, missing_required after file).
- [x] **Step 5 — InstanceLock**: `daemon/lock.py` — acquire (pid file + liveness), reclaim stale, release; context manager. [BR-G3]
- [x] **Step 6 — Lock tests**: `tests/unit/test_lock.py` (acquire/release, stale reclaim, double-acquire fails).
- [x] **Step 7 — Config edit**: `config/editor.py` (`ConfigEditor.read/apply` via injected Provisioner; reducer; hot-reload signal; read-back + health verify → `ConfigResult`; `ReadOnlyError`), `config/service.py` (`ConfigService` local-only). [FR-E1..E3; Q2/Q4; BR-E*]
- [x] **Step 8 — Config tests**: `tests/unit/test_config_service.py` (get/set, remote ReadOnlyError, apply happy + verify, apply failure → verified=false) with `FakeProvisioner`; PBT-U4-4 (remote read-only) appended to pbt file.
- [x] **Step 9 — Composition wiring**: `daemon/wiring.py` — `build_services(settings)`: Registry(load), SbxProvisioner, ImageBuilder, HealthChecker(HealthProbes incl. U3 `transport_healthy`), AgentService, ChatService, Supervisor(restart=local serve restart, mark_failed), AIGatewayService app. Returns a `Services` container. [BR-W1/W2]
- [x] **Step 10 — Control API**: `daemon/control_api.py` — `build_control_app(services)`: agents CRUD/stop/start, chat & logs SSE (ChatEvent.to_dict), config get/put, `/status`, `/healthz`; error→JSON boundary; AgentView projection. [FR-G3; C4]
- [x] **Step 11 — Control API tests**: `tests/unit/test_control_api.py` — in-process ASGI client over fakes: list returns secret-stripped views, chat SSE streams events, config put returns result, status shape, error mapping, remote config 4xx.
- [x] **Step 12 — GatewayService**: `daemon/gateway.py` — `start(foreground, daemonize)` (bootstrap config Q3 → lock → build_app → run listeners → Supervisor.start), `stop` (graceful), `status`, `build_app`, `_daemonize` + signal handlers. uvicorn-serve and fork paths isolated + **Build&Test-flagged**; pure parts (build_app/status/bootstrap) unit-testable. [FR-G1..G4]
- [x] **Step 13 — CLI**: `cli/client.py` (`ControlAPIClient` httpx unary+SSE, `is_daemon_up`), `cli/render.py` (human/json + EXIT codes 0/2/1), `cli/app.py` (typer handlers for all commands; interactive `chat`; daemon-down guidance), `__main__.py`. [C1/C2; Q6]
- [x] **Step 14 — CLI tests**: `tests/unit/test_cli.py` — `CliRunner` + `FakeControlAPIClient`: `agent ls`/`--json`, exit codes, `gateway status`, daemon-down message; extend `tests/fakes.py`.
- [x] **Step 15 — Packaging**: `pyproject.toml` — add `typer>=0.12`; `[project.scripts] caduceus = "caduceus.cli.app:app"`. Install into `.venv`.
- [x] **Step 16 — Summaries**: `aidlc-docs/construction/u4-cli-daemon-config/code/{business-logic-summary,api-layer-summary}.md`.
- [x] **Step 17 — Sanity run**: `pytest` in `.venv` (all units). Expect U1+U2+U3+U4 green.

## Traceability
- FR-G1..G4 (Steps 5,9,10,12,13) · FR-E1..E3 (Steps 1,7,8) · FR-L1 (Steps 10,13).
- PBT-U4-1..6 (Steps 2,8 + pbt file). Composition wiring BR-W1/W2 (Step 9).

## Notes
- New runtime dep: **`typer>=0.12`** + console script. No other new deps (httpx/fastapi/uvicorn/websockets present).
- uvicorn `Server.serve()`, `-d` fork/setsid, and real sbx/hermes are **unit-untested by design** (Build & Test) — same convention as U2 `SbxProvisioner` / U3 `ServeTransport`. Unit tests cover wiring/build_app/routes/CLI/config/lock/dtos.
- Build & Test validation items tracked in U4 Infra Design (daemonize, console script, bootstrap, AC-2..AC-7, reload mechanism, graceful degradation).
