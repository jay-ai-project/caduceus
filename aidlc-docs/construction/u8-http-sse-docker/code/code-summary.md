# U8 — Code Generation Summary (HTTP/SSE Transport + Docker Runtime)

All 17 plan steps executed (brownfield, in-place). **241 unit+PBT tests pass** (was 211; +30).
No new runtime dependency (dropped `websockets`; `httpx` already present). Live Docker +
hermes-API-server integration is deferred to Build & Test.

## Created
- `caduceus/transport/hermes_api.py` — `HermesApiTransport` (HTTP+SSE): session create/reuse,
  `/api/sessions/{id}/chat/stream` SSE→ChatEvent mapping, run_id capture + Runs `stop`,
  `/health`, `/api/sessions/{id}/messages` history.
- `caduceus/config/doctor.py` — `run_doctor()` + `DoctorReport`/`Check` (Docker/image/runtime/
  gVisor/daemon checks; gVisor install guidance; never installs).
- `tests/unit/test_hermes_api_transport.py`, `tests/unit/test_doctor.py`,
  `tests/pbt/test_u8_properties.py` (PBT-U8-1..5).

## Modified
- `common/models.py` — AgentRecord: `sandbox_name`→`container_name`, `serve_port`→`host_port`,
  drop `serve_auth`, add `runtime`.
- `common/settings.py` — `container_runtime` (env/file/write).
- `common/dto.py` — GatewayConfigChange/View gain `container_runtime`; drop stale serve_auth note.
- `transport/base.py` — `for_agent`→`HermesApiTransport`; `TransportKind.http`; docstrings.
- `transport/chat.py` — HTTP-oriented warm/history/comments; close history transport.
- `transport/supervisor.py` — restart = docker start; HTTP health comments.
- `agents/provisioner.py` — `SbxProvisioner`→`DockerProvisioner` (docker CLI:
  create/host_port/put_file/stop/start/remove/status/statuses/logs; runsc fail-fast via
  `RuntimeUnavailable`); removed `SandboxSnapshot`/`list_statuses`.
- `agents/images.py` — docker-build-only (removed `sbx template load`).
- `agents/hermes_config.py` — `api_server_env()`; remote guidance → API-server URL.
- `agents/health.py` — `HealthProbes(agent_reachable, upstream_reachable)`; shallow=HTTP `/health`.
- `agents/names.py` — `sandbox_name`→`container_name`; Docker-safe regex.
- `agents/service.py` — Docker create saga (create→host_port→endpoint→put_file→start→
  await_ready→warm→health); real-time parallel no-cache `list`; `reconcile_all` via `statuses`;
  `runtime_provider` (live hot-apply).
- `config/gateway_config.py` — `validate_runtime`, `container_runtime` in view/persist/apply,
  ENV_KEYS.
- `daemon/wiring.py` — DockerProvisioner, HTTP `agent_reachable` probe, `runtime_provider`.
- `daemon/gateway.py` — boot-reconcile/shutdown comments (docker/HTTP; behavior unchanged).
- `daemon/control_api.py` — logs route uses `container_name`.
- `cli/app.py` — `caduceus doctor`; `gateway config --runtime`.
- `cli/render.py` — `render_doctor`; runtime in config views + env-warning.
- `images/hermes/Dockerfile` — install base hermes + aiohttp; `CMD hermes gateway run`;
  `HERMES_ACCEPT_HOOKS=1`; removed `[acp]`.
- `pyproject.toml` — drop `websockets`.
- `README.md` — container/HTTP-SSE/gVisor/doctor; drop sbx/ACP.
- Tests: `tests/fakes.py` (Docker Protocol + HTTP FakeTransport + runtime in config fakes),
  `test_models`, `test_names`, `test_agent_service`, `test_dto`, `test_gateway_config`,
  `test_control_api_gateway_config`, `test_cli`, `test_control_api` (phrase),
  `pbt/{test_registry_properties,test_u4_properties,test_u7_properties}`.

## Deleted
- `caduceus/transport/acp.py`, `caduceus/transport/serve.py`, `tests/unit/test_acp_transport.py`.

## Residual (confirm in Build & Test — live)
- hermes create-session response id field name + `/messages` payload shape (defensive parse).
- Dockerfile: `hermes gateway run` present + `aiohttp` sufficient for the API-server platform.
- Whether `/health` is auth-exempt (we send Bearer regardless).
- runsc end-to-end on a host with gVisor installed.
