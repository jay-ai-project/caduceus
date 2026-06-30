# U4 CLI / Daemon / Config — API / Test Summary (code)

## Public surface
- **Console script** `caduceus = caduceus.cli.app:main` (registered in `pyproject.toml`); `python -m caduceus` equivalent.
- **Control API** (`build_control_app`): `POST /agents`, `POST /agents/register`, `GET /agents`, `DELETE /agents/{name}`, `POST /agents/{name}/stop|start`, `POST /agents/{name}/chat` (SSE), `GET|PUT /agents/{name}/config`, `GET /agents/{name}/logs` (SSE), `GET /healthz`, `GET /status`.
- **AI-Gateway** (U1) mounted on the second listener by the daemon (`build_services` → `aigateway_app`).

## Tests (all green: `pytest` → 132 passed; U4 contributes 51)
| File | Covers |
|---|---|
| `tests/unit/test_dto.py` | DTO round-trips; reducer (basic, idempotent, disable-wins); `resolve_strategy` + seam; `snapshot_satisfies`; secret-stripping |
| `tests/unit/test_settings_file.py` | env > file > default; write/read round-trip; missing-required |
| `tests/unit/test_lock.py` | acquire/release; double-acquire blocked; stale reclaim; context manager |
| `tests/unit/test_config_service.py` | apply happy + verified; not-verified on no-op write; remote read-only (get+set); soul conflict; empty no-op |
| `tests/unit/test_control_api.py` | ASGI: healthz/status; list secret-stripped; create; chat SSE; config get/put; remote config 409; logs local-only |
| `tests/unit/test_cli.py` | CliRunner: `ls` human/`--json`; daemon-down exit 1; create; rm error→exit; config usage errors (no opts / soul conflict); config set; chat once; gateway status down/`--json` |
| `tests/pbt/test_u4_properties.py` | PBT-U4-1 DTO round-trip; -2 reducer idempotent + read-back; -3 no-secret projection; -4 remote always read-only; -5 reload-strategy totality + seam; -6 exit-code totality |

Test doubles added to `tests/fakes.py`: `FakeAgentService`, `FakeChatService`, `FakeConfigService`, `build_fake_services`, `FakeControlAPIClient`.

## Not unit-tested by design (→ Build & Test)
- `GatewayService._serve` (uvicorn serving), `_daemonize` (fork/setsid), real `ControlAPIClient` over TCP, sandbox config read/write/reload codec. Validated in Build & Test (AC-1..AC-7, daemonize/lock, hermes reload mechanism, graceful degradation).

## PBT-08
- Hypothesis seed/repro logging via the existing `tests/conftest.py` profile (shared across units).
