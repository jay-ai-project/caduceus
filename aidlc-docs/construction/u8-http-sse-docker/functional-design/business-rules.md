# U8 Functional Design — Business Rules

Prefixes: **BR-T** transport/chat, **BR-D** docker/provisioner, **BR-R** runtime/gVisor,
**BR-N** networking/security, **BR-O** ops (doctor/config/lifecycle). Carries forward the
invariants named in U3/U5/U7.

## Transport & Chat (BR-T)
- **BR-T1** — A single `HermesApiTransport` (HTTP+SSE) serves **all** agents; there is no
  per-`AgentKind` transport branch. (Q7)
- **BR-T2** — Chat turns run against the agent's **persistent session**
  (`/api/sessions/{sid}/chat/stream`); `session_id` is created lazily and auto-recreated
  transparently if the backend reports it missing (recreate at most once per turn). (U3 Q1=A)
- **BR-T3** — Every turn passes through `normalize_stream`: zero+ `token`/`thinking`/
  `tool_call`/`message` events then **exactly one** terminal (`done` XOR `error`); nothing
  follows a terminal — regardless of `run.completed`/`done` ordering. (terminal invariant)
- **BR-T4** — `assistant.delta`→`token`; `tool.progress[_thinking]`→`thinking`;
  `tool.*`→`tool_call` with `meta` (id/name/status/input/output); mapping is defensive
  (unknown events ignored, never raise). (U5 compat)
- **BR-T5** — `request_cancel` ends the turn with `done{cancelled=true}`: via
  `POST /v1/runs/{run_id}/stop` when `run_id` is known, else SSE disconnect. Cooperative,
  idempotent, single terminal. (U3 Q6)
- **BR-T6** — Health checks use `GET /health` only and **never** spend an LLM completion.
  (BR-C11 preserved)
- **BR-T7** — History (`load_history`) is best-effort via `/api/sessions/{sid}/messages`;
  errors → empty list, never raise into the caller. (FR-W10)
- **BR-T8** — `close()` tears down only the HTTP client/SSE — **never** the container.

## Docker Provisioner (BR-D)
- **BR-D1** — Local agents run as plain Docker containers named `cad-<name>`; entrypoint
  `hermes gateway run` with the API-server platform enabled. `sbx` is not used anywhere.
- **BR-D2** — The hermes API port (8642) is published to **`127.0.0.1` only**, on a
  Docker-assigned ephemeral host port, read back and stored as `host_port`/`endpoint`. (Q2)
- **BR-D3** — Container `status` and the running-container list are queried **live** per call
  (no cache/snapshot). Any provisioner error is caught and reported; it must not crash
  `agent ls`. (NFR-U8-P1)
- **BR-D4** — Secrets (bearer token) reach the container via `-e`/stdin-written 600-perm files,
  never on a logged command line; tokens are never logged. (SECURITY-03)
- **BR-D5** — The hermes image is built with `docker build` and used directly by `docker run`;
  there is no image-store bridging step. Image/version pinned (no `latest`). (SECURITY-10)

## Runtime / gVisor (BR-R)
- **BR-R1** — Default container runtime is **`runc`**; `runsc` (gVisor) is opt-in via config.
  caduceus never installs gVisor. (Q4/Q5)
- **BR-R2** — If the configured runtime is `runsc` but it is not available/registered with
  Docker, agent creation **fails fast** with actionable guidance — **no silent fallback** to
  `runc`. (Q4=A)
- **BR-R3** — `container_runtime` config accepts only `runc`|`runsc` (validated); invalid
  values are rejected with a clear message. Applies to newly-spawned containers only;
  existing containers keep their runtime until recreated. (Q5)

## Networking / Security (BR-N — advisory, Q9)
- **BR-N1** — Agent API servers are bound so they are reachable on **loopback only**
  (`-p 127.0.0.1:…`); never `0.0.0.0` on the host. (SECURITY-07 spirit)
- **BR-N2** — Every caduceus→agent request carries `Authorization: Bearer <token>`; the agent's
  `API_SERVER_KEY` equals that token; a missing/invalid token is rejected by hermes. (SECURITY-08)
- **BR-N3** — Agent→AI-Gateway outbound routing (bridge gateway IP `:9701`) is unchanged;
  only the inbound direction is new. Errors fail closed and do not leak internals into chat
  errors. (SECURITY-15)
- **BR-N4** — Security findings this cycle are **advisory (non-blocking)** but must be
  surfaced in stage completion summaries. (Q9)

## Ops: doctor / config / lifecycle (BR-O)
- **BR-O1** — `caduceus doctor` reports readiness (docker, image, runtime availability,
  AI-Gateway reachability) and prints gVisor install guidance when `runsc` is desired but
  missing; it **never** installs or mutates the system. (Q3)
- **BR-O2** — `gateway stop` does **not** tear down agent containers; on daemon boot, running
  `cad-*` containers are reconciled/reattached (host_port/endpoint recomputed) → `running`.
  (U7 lifecycle decoupling + boot reconcile preserved)
- **BR-O3** — The supervisor supervises only `running` local agents for auto-restart; it does
  not gate the `agent ls` read path (which is live). (U7 preserved)
- **BR-O4** — Remote agents keep a **read-only lifecycle** (no start/stop/rm); `register`
  guidance points at the hermes **API server** URL + token. (Q7, BR-A10 preserved)
- **BR-O5** — Tool approval is **auto** in v1: approval events are surfaced for visibility but
  caduceus does not block a turn awaiting approval. (Q8)
