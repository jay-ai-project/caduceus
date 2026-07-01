# U8 — Code Generation Plan (HTTP/SSE Transport + Docker Runtime)

Single source of truth for U8 generation. Brownfield: **modify in place**, never duplicate.
Follows the FD critical path. Rule/PBT traceability in each step. Tests run in Build & Test.

**Scope**: unify transport to HTTP/SSE (`HermesApiTransport`), replace `sbx` with Docker
(`DockerProvisioner`), docker-build-only image, optional `runsc`, `caduceus doctor`,
`gateway config --runtime`, real-time no-cache `ls`. Remove ACP/serve. Preserve every U1–U7
invariant except the (intentionally dropped) U7 fast-`ls` cache.

---

## Step 1 — Domain model reshape (`common/models.py`)  [x]
- `AgentRecord`: **drop** `serve_port`, `serve_auth`; **add** `host_port: Optional[int]`,
  `container_name: Optional[str]` (replaces `sandbox_name`), `runtime: str = "runc"`.
- Keep `endpoint` (now set for local too). Update `to_dict`/`from_dict` (round-trip; PBT).
- (BR-D1/D2, FR-U8-14)

## Step 2 — Settings: container runtime (`common/settings.py`)  [x]
- Add `container_runtime: str = "runc"` (env `CADUCEUS_CONTAINER_RUNTIME`, file key
  `container_runtime`); include in `from_env`, `from_env_and_file`, `write_config_toml`.
- (BR-R1/R3, FR-U8-12)

## Step 3 — SSE→ChatEvent mapping + `HermesApiTransport` (`transport/hermes_api.py` NEW)  [x]
- New `HermesApiTransport(Transport)` over `httpx` (async) + an SSE line reader:
  - `open()`: ensure session (reuse `rec.session_id` or `POST /api/sessions`); `state=open`.
  - `_raw_stream()`: `POST /api/sessions/{sid}/chat/stream`, parse `event:/data:` frames, map
    per domain-entities table (assistant.delta→token; tool.progress[_thinking]→thinking; other
    tool.progress + tool.started/completed/failed→tool_call w/ `meta`; run.completed/done→done;
    error→error). Capture `run_id` from `run.started`. Session-missing → recreate once + retry.
  - `request_cancel()`: `POST /v1/runs/{run_id}/stop` if run_id known, else disconnect; ends
    `done{cancelled}`.
  - `health()`: `GET /health` (Bearer) → shallow HealthStatus, **no LLM** (BR-T6).
  - `is_alive()`: state==open (HTTP is stateless; reusable across turns).
  - `load_history(sid)`: `GET /api/sessions/{sid}/messages` → `[HistoryTurn]`, best-effort.
  - `close()`: close httpx client only (never the container; BR-T8).
- All raw streams already go through `normalize_stream` in `Transport.chat_stream` (BR-T3).
- (BR-T1..T8, PBT-U8-1/-5)

## Step 4 — Transport factory + retire ACP/serve (`transport/base.py`, delete files)  [x]
- `Transport.for_agent(rec)` → always `HermesApiTransport` (no `AgentKind` branch; BR-T1).
- `TransportKind`: replace `serve`/`acp` with `http`.
- **Delete** `transport/acp.py` and `transport/serve.py`.

## Step 5 — DockerProvisioner (`agents/provisioner.py`)  [x]
- Replace `SbxProvisioner` with `DockerProvisioner` over the `docker` CLI; update the
  `Provisioner` Protocol. Remove `SandboxSnapshot` + `sbx ls` snapshot model.
  - `create(container, image, env, runtime, workspace)`: `docker run -d --name … -p
    127.0.0.1::8642 [--runtime <r>] --restart no -v ws:ws -e …`; **runsc fail-fast** (BR-R2);
    read published host port back (`docker inspect`) → return it.
  - `write_file` (docker exec -i, chmod 600, secrets off argv; BR-D4), `stop`/`start`/`remove`,
    live `status` (`docker inspect`, no cache; BR-D3), `list_running` (`docker ps` filter),
    `host_port`, `logs` (`docker logs`).
- (BR-D1..D5, PBT-U8-3)

## Step 6 — Image build docker-only (`agents/images.py`)  [x]
- Build via `docker build`; **remove** `docker save | sbx template load` and all `sbx`
  references. `ensure_image` = build-if-absent, return tag. (BR-D5)

## Step 7 — hermes config + API-server env (`agents/hermes_config.py`)  [x]
- Keep `render_hermes_config` (LLM provider → AI-Gateway). Add `api_server_env(token, port=8642)`
  → `{API_SERVER_ENABLED, API_SERVER_KEY, API_SERVER_HOST, API_SERVER_PORT}` (D4/D5, BR-N2).
- Update `remote_setup_guidance` to describe the hermes **API server** URL + token. (BR-O4)

## Step 8 — Health unify over HTTP (`agents/health.py`)  [x]
- Shallow signal for **both** kinds = `GET /health` reachable (via injected
  `endpoint_reachable`); drop the `sandbox_status` batch param + sbx-running signal.
- Deep = upstream reachable + transport `/health` (no LLM). (BR-T6, FR-U8-7)

## Step 9 — Names → container name (`agents/names.py`)  [x]
- `sandbox_name` → `container_name` (`cad-<name>`), keep `validate_name`. Update callers.

## Step 10 — AgentService: create/list/reconcile/lifecycle (`agents/service.py`)  [x]
- `create` saga: ensure image → `docker run` (runtime from settings) → read host_port → set
  `endpoint=http://127.0.0.1:<hp>` → write hermes config + api-server env → warm (session, no
  LLM) → health. Store `container_name`/`host_port`/`runtime` on record. Compensate on failure.
- `list(probe=True)`: **real-time, parallel, no cache** — `asyncio.gather` per-agent `/health`
  (bounded, per-probe timeout) + live `docker inspect`; compose lifecycle+health per request.
  `probe=False` → registry projection (no snapshot cache). Remove `SandboxSnapshot` usage.
- `reconcile_all` (boot): `docker ps` → reattach running `cad-*` (recompute host_port/endpoint)
  → running; else stopped. `stop/start/remove` via docker. Pass `container_runtime`.
- (NFR-U8-P1/P2, BR-O2/O3, PBT-U8-4)

## Step 11 — Chat + Supervisor doc/health (`transport/chat.py`, `transport/supervisor.py`)  [x]
- chat.py: warm()/history() now apply to local HTTP agents (kind==local); pool reuse works
  (HTTP `is_alive`). Update ACP-era comments. history via generic `load_history`.
- supervisor.py: health via HTTP; `restart` = docker start (injected); comments serve→gateway;
  supervises only `running` (BR-O3). Keep circuit breaker/backoff.

## Step 12 — Daemon wiring + boot reconcile (`daemon/wiring.py`, `daemon/gateway.py`)  [x]
- Wire `DockerProvisioner`, HTTP `endpoint_reachable` probe (httpx `/health`), transport health;
  `Transport.for_agent`→HTTP; pass `settings.container_runtime`. Boot: `reconcile_all()`;
  `gateway stop` leaves containers (BR-O2). Supervisor restart hook = docker start.

## Step 13 — Config runtime surface (`config/gateway_config.py`, `common/dto.py`, control_api)  [x]
- `GatewayConfigView`/`GatewayConfigChange` (+dto): add `container_runtime`; validate ∈
  {runc,runsc}; atomic key-preserving persist (reuse U6 store). Extend `GET/POST /gateway/config`.
- (BR-R3, FR-U8-12)

## Step 14 — `caduceus doctor` (`cli/app.py`, `cli/client.py`, `cli/render.py`, dto)  [x]
- CLI-local command (works daemon up or down): checks docker present/version, hermes image
  present, configured runtime availability (`docker info` runtimes / `runsc` on PATH), and
  AI-Gateway/control reachability. Prints gVisor install guidance when `runsc` desired+missing
  (never installs). Human + `--json`; non-zero exit on required-check failure. Add
  `gateway config --runtime runc|runsc` to CLI + render. (BR-O1, BR-R2, FR-U8-11)

## Step 15 — Image Dockerfile + deps (`images/hermes/Dockerfile`, `pyproject.toml`)  [x]
- Dockerfile: install hermes extra that ships the **gateway + aiohttp** (replace `[acp]`);
  ensure `hermes gateway run`; set entrypoint/CMD to `hermes gateway run`. Keep pinned
  version/git-ref (BR-D5). pyproject: httpx already present; drop `websockets` (serve-only).

## Step 16 — Tests: fakes + unit + PBT (`tests/…`)  [x]
- `tests/fakes.py`: `FakeProvisioner` (docker semantics: create→host_port, live status,
  list_running), `FakeHermesApiTransport` / fake SSE server, HTTP `endpoint_reachable` fake.
  Remove ACP/serve fakes.
- Update unit tests: agent_service, chat_service, supervisor, control_api, cli, transport
  (mapping). Delete acp/serve tests. New `tests/pbt/test_u8_properties.py` (PBT-U8-1..5).

## Step 17 — Docs (`aidlc-docs/construction/u8-http-sse-docker/code/code-summary.md`, `README.md`)  [x]
- Code summary (modified/created/deleted files, test delta). Update README (Docker/runsc/doctor,
  drop sbx/ACP; `gateway config --runtime`).

---

### Notes on test authoring
Per the project's Test Delegation workflow, once code is functionally complete this cycle's
tests will be delegated to a **`fork`** subagent (`e2e-test-writer` conventions) and the live
suite run by the **`e2e-test-runner`** in Build & Test.
