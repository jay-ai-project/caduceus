# U8 Functional Design — Business Logic Model

Logic units (L*) for the HTTP/SSE + Docker migration, with the inline design decisions
(requirements + spike resolved the unknowns; no separate question round — matches U5–U7 rhythm).

## Inline Decisions (D*)
- **D1 — One transport**: `HermesApiTransport` (HTTP + SSE) for **both** local & remote.
  `AcpTransport` + `ServeTransport` deleted; `Transport.for_agent` returns `HermesApiTransport`
  for every agent (no `AgentKind` protocol branch). `Transport` contract unchanged.
- **D2 — Turns via Sessions, stop via Runs**: chat uses `POST /api/sessions/{sid}/chat/stream`
  (richest events + persistent session + history); `run_id` captured from `run.started` powers
  `POST /v1/runs/{run_id}/stop`. Cancel before `run.started` → SSE client disconnect.
- **D3 — Docker host port**: publish `-p 127.0.0.1::8642` (Docker assigns an ephemeral host
  port), then read it back via `docker inspect`/`docker port` → `AgentRecord.host_port` →
  `endpoint`. Avoids port-selection races.
- **D4 — One token per agent**: `token` = caduceus→agent Bearer **and** in-container
  `API_SERVER_KEY`. Outbound LLM auth (agent→AI-Gateway) keeps the existing inline `api_key`.
- **D5 — Container entrypoint**: `hermes gateway run` with env `API_SERVER_ENABLED=true`,
  `API_SERVER_KEY=<token>`, `API_SERVER_HOST=0.0.0.0`, `API_SERVER_PORT=8642`; hermes LLM
  config (existing `render_hermes_config`) points at the caduceus AI-Gateway.
- **D6 — Real-time, no cache**: `agent ls` computes state live every call (D-below L5).

---

## L1 — HermesApiTransport (transport/hermes_api.py)
Replaces acp.py/serve.py. Uses an async HTTP client (httpx; already a dep) + an SSE reader.
- `open()`: ensure a session — reuse `rec.session_id` if set, else `POST /api/sessions`,
  store id. Set `state=open`. No LLM spend.
- `_raw_stream(session_id, message)`: `POST /api/sessions/{sid}/chat/stream`, read SSE lines,
  map per the domain-entities table, yield `ChatEvent`s. Capture `run_id` from `run.started`
  into `self._run_id`. On session-missing (404/invalid session) → recreate session once and
  retry (transparent recreate, U3 Q1=A). `chat_stream` wraps via `normalize_stream`.
- `request_cancel()`: set `_cancelled`; if `_run_id` known → best-effort
  `POST /v1/runs/{run_id}/stop`; else close the SSE response. Stream ends `done{cancelled}`.
- `health()`: `GET /health` (Bearer) → shallow `HealthStatus`; never chats (BR-C11).
- `is_alive()`: cheap — `state==open` and last stream not broken (HTTP conn is stateless, so
  a transport is reusable across turns unless a hard error occurred).
- `load_history(sid)`: `GET /api/sessions/{sid}/messages` → `[HistoryTurn]`; best-effort,
  text-only; empty on error.
- `close()`: close the HTTP client; `state=closed`. **No** container teardown (that's the
  provisioner's / lifecycle's job).

## L2 — DockerProvisioner (agents/provisioner.py)
Replaces `SbxProvisioner`; same `Provisioner` Protocol (minus sbx specifics), via `docker` CLI.
- `create(container, image, env, runtime, host_bind)`: `docker run -d --name <container>
  -p 127.0.0.1::8642 --restart no [--runtime <runtime>] -v <ws>:<ws> -e ...env...
  <image>` (entrypoint = `hermes gateway run`, baked in image or passed). Then read published
  host port via `docker inspect`. **Runtime fail-fast**: if `runtime==runsc` and `docker run`
  fails with unknown-runtime, raise a clear guidance error (BR-R2) — no silent `runc`.
- `write_file(container, path, content)`: `docker exec -i <container> sh -lc 'cat > path;
  chmod 600'` via stdin (keeps secrets off argv), for the hermes config.
- `stop`/`start`/`remove`: `docker stop|start|rm -f`.
- `status(container)`: **live** `docker inspect -f '{{.State.Status}}'` → running|exited|
  missing (no cache).
- `list_running()`: single `docker ps --filter name=cad- --format ...` (live snapshot for
  reconcile; still real-time, not cached).
- `host_port(container)`: `docker port <container> 8642` / inspect.
- `logs(container, follow)`: `docker logs [-f] <container>`.

## L3 — Image build (agents/images.py)
- `docker build` from `images/hermes/Dockerfile` → tag; used **directly** by `docker run`.
- **Remove** the `sbx template load` bridging entirely (Finding D no longer applies).
- Dockerfile: install hermes with the extra that ships the **gateway + aiohttp** (replace
  `[acp]`); ensure `hermes gateway run` present; keep pinned version/git-ref (SECURITY-10).

## L4 — Health (agents/health.py + transport)
- Shallow signal unified: **local and remote both have `endpoint`** → shallow = `GET /health`
  reachable (200). Local no longer keys off sandbox running; container `status` is used only
  by reconcile/lifecycle, not as the health signal.
- Deep (no LLM spend): upstream reachable (U1) + transport `/health` OK (+ optionally
  `/v1/models`). Removes the sandbox_status batch param (no snapshot).

## L5 — AgentService list / create / warm-up (agents/service.py)
- **`list(probe=True)` — real-time, parallel, no cache (NFR-U8-P1)**: for all agents,
  probe `/health` **concurrently** (`asyncio.gather`, bounded, per-probe timeout) and read
  live container status; compose lifecycle + health per request. No `last_health` read for the
  authoritative view. `probe=false` (Web UI dashboard) → registry projection (fast) as today,
  but **without** the removed snapshot cache.
- **create saga (U7 preserved)**: register `creating` → background: ensure image → `docker run`
  → read host_port/endpoint → write hermes config → wait `/health` OK → create session
  (**warm-up**, no LLM) → `running`/`healthy`. `--wait` blocks; failure → `failed` + detail;
  compensate (best-effort `docker rm`).
- Warm-up = container `/health` OK + session created, so first turn has no cold stall
  (NFR-U8-P2).

## L6 — Supervisor (transport/supervisor.py)
- Unchanged responsibility (auto-restart/resiliency, circuit breaker). Health probe now HTTP
  `/health`. Supervises only `running` local agents. Updates `last_health` for observability;
  the `ls` read path no longer depends on it (D6). `gateway stop` does not stop containers
  (U7 decoupling preserved).

## L7 — Daemon wiring / boot reconcile (daemon/wiring.py, gateway.py, control_api.py)
- Wiring assembles `HealthProbes` with an HTTP `/health` probe + live `docker` status; injects
  `DockerProvisioner`; `Transport.for_agent` → `HermesApiTransport`.
- **Boot reconcile (U7 preserved)**: on daemon start, `docker ps` for `cad-*` → reattach
  running containers (recompute host_port/endpoint) → `running`; absent → `stopped`.
- Control API gains: `GET/POST /gateway/config` extended with `container_runtime`; new
  `doctor` route (or CLI-local); `GET /agents/{name}/history` now via `/messages`.

## L8 — `caduceus doctor` (cli + control_api)
- Checks: `docker` present + version; hermes image present; configured `runtime` availability
  (`docker info` runtimes / `runsc` on PATH); AI-Gateway reachability. Prints gVisor install
  guidance when `runsc` desired but missing (**never installs**, Q3/Q4). Human + `--json`;
  exit code non-zero if a *required* check fails.

## L9 — Runtime config (config/gateway_config.py, settings.py)
- `Settings.container_runtime` (env `CADUCEUS_CONTAINER_RUNTIME`, file `container_runtime`,
  default `runc`). `gateway config --runtime runc|runsc` validates ∈ {runc,runsc}, persists to
  `config.toml` (atomic key-preserving write, reuse U6 store), shows in `--get`/`--json`.
  Applies to **newly-spawned** containers (existing keep their runtime until recreated).

---

## Property-Based Testing targets (PBT full)
- **PBT-U8-1 — SSE mapping totality + terminal invariant**: for arbitrary sequences of hermes
  SSE events (incl. malformed/interleaved/duplicated terminals), `_raw_stream`→`normalize_stream`
  yields a valid stream ending in exactly one terminal; never raises; thinking/tool/token
  mapping preserved.
- **PBT-U8-2 — runtime-selection validation totality**: `validate_runtime(x)` total over
  arbitrary strings → accepts only {runc,runsc}, else a clear error; idempotent persist.
- **PBT-U8-3 — DockerProvisioner state machine (stateful)**: create/stop/start/remove vs a
  reference model; `status` never contradicts the model; missing→create ok; double-remove safe.
- **PBT-U8-4 — real-time list determinism**: `list` output is a pure function of the live
  (provisioner status + health probe) inputs — no dependence on cached `last_health`.
- **PBT-U8-5 — cancel/stop safety**: `request_cancel` at any point yields a terminal
  `done{cancelled}` exactly once (no double-terminal, no post-terminal events).
