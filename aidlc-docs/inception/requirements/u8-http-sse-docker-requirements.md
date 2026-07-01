# U8 — HTTP/SSE Transport + Docker Runtime Migration — Requirements

## Intent Analysis
- **User request**: Replace the `hermes acp` + `sbx` local-agent stack with the official
  **hermes API Server** (HTTP + SSE) and **plain Docker containers**; unify the Local/Remote
  transport branch; add **gVisor (`runsc`) as an optional container runtime**.
- **Request type**: Migration + Refactoring (re-architecture of an existing, working system).
- **Scope estimate**: System-wide (transport, agent provisioning, image build, health,
  daemon lifecycle, CLI/config, docs).
- **Complexity**: Complex / high-risk (swaps the agent runtime **and** the transport
  protocol; changes the network trust boundary).
- **Brownfield**: Yes — builds on U1–U7 (AI-Gateway, registry/provisioner, transport/chat,
  daemon/CLI/config, Web UI, gateway config, perf/stability).

## Terminology (locked)
- **hermes API server** = the per-agent HTTP/SSE server started by `hermes gateway` inside a
  container. (hermes docs call it a "gateway"; we do **not** reuse that word to avoid
  collision.)
- **gateway** / **caduceus gateway** = the caduceus daemon (AI-Gateway + Control API + Web UI).

## Decisions Locked (from verification questions)
| Q | Decision |
|---|---|
| Q1 | **A** — Transport standardizes on **Sessions + Runs** composed: persistent per-agent session (`/api/sessions`, `/api/sessions/{id}/chat/stream` SSE, `/api/sessions/{id}/messages`) + Runs API for stop/approval/events. |
| Q2 | **A** — Inbound via **host loopback publish**: `docker run -p 127.0.0.1:<hostPort>:8642`; caduceus connects to `http://127.0.0.1:<hostPort>`. Host port allocated + recorded per agent. |
| Q3 | **A** — New **`caduceus doctor`** command: checks Docker + hermes image + `runsc` availability; prints gVisor install guidance when missing (never auto-installs). |
| Q4 | **A** — `runsc` configured but unavailable → **fail fast with guidance** (no silent downgrade). |
| Q5 | **A** — Runtime selected via **`caduceus gateway config --runtime runc\|runsc`** (shown in `--get`/`--json`, persisted to `config.toml`), applied to newly-spawned containers. |
| Q6 | **A (strengthened by user)** — **No legacy at all.** The module has never been deployed (solo dev); there are **zero** existing agents. `sbx` is forgotten entirely — no migration, no legacy records, no fallback. Clean, Docker-container-only state. |
| Q7 | **A** — **One HTTP/SSE transport** for both local & remote; drop `AcpTransport` + `ServeTransport`. Local = caduceus-managed container; remote = user-registered hermes **API server** URL + bearer, lifecycle read-only. |
| Q8 | **A** — **Auto-approve**, surface tool-call events for visibility; approval endpoint wired but not blocking. |
| Q9 | **Security Baseline = enabled, best-effort/advisory (non-blocking)**; Resiliency = Yes (full); PBT = Yes (full). |

---

## Functional Requirements

### FR-U8-1 — hermes API server as the agent runtime (in-container)
- Each local agent container runs a long-lived **`hermes gateway`** process with the API
  server enabled, bound to `0.0.0.0:8642` **inside** the container, protected by a bearer
  token (`API_SERVER_KEY`) equal to the agent's caduceus-issued token.
- The container image provides `hermes gateway` and enables the API server via env
  (`API_SERVER_ENABLED=true`, `API_SERVER_KEY`, `API_SERVER_HOST`, `API_SERVER_PORT`).

### FR-U8-2 — Single unified HTTP/SSE transport
- Introduce one transport (e.g. `HermesApiTransport`) that speaks the hermes API server over
  HTTP + SSE for **all** agents (local and remote). `AcpTransport` and `ServeTransport` are
  removed; `Transport.for_agent` no longer branches on `AgentKind` for protocol selection.
- The transport preserves the existing `Transport` contract: `open/close/health`,
  `chat_stream` (terminal-guarded via `normalize_stream`), cooperative `request_cancel`,
  and best-effort `load_history`.

### FR-U8-3 — Chat + streaming over SSE
- Chat turns run against the agent's **persistent session** using
  `POST /api/sessions/{id}/chat/stream` (SSE). SSE events map to caduceus `ChatEvent`s:
  assistant token deltas → `token`/`message`, thinking → `thinking`, tool started/completed
  → `tool_call` (preserving the U5 `meta`/`ToolCallMeta` model), completion → terminal `done`.
- Session lifecycle: one persistent session per agent, auto-created on first use and
  auto-resumed (matches current behavior). The session id is stored on `AgentRecord`.

### FR-U8-4 — Stop / cancel
- `request_cancel` maps to the Runs API stop (`POST /v1/runs/{run_id}/stop`) for the active
  run, ending the stream with `done{cancelled=true}` (preserving the terminal-event
  invariant). If no run-id is known, cancel degrades gracefully (client-side stream close).

### FR-U8-5 — Approval (auto)
- Tool-call approval is **auto-approved** (Q8=A): the agent runs autonomously. Approval
  events are surfaced in the stream for visibility (as `tool_call` events) but caduceus does
  not block. The approval endpoint may be wired for future interactive mode but is not used
  to gate turns in v1.

### FR-U8-6 — Session history
- `ChatService.history()` / `GET /agents/{name}/history` (U5) is served from
  `GET /api/sessions/{id}/messages` instead of the ACP `session/load` replay. Best-effort,
  text-first, mapped to the existing `HistoryTurn` model.

### FR-U8-7 — Health over HTTP (real-time, no cache)
- Health checks use the hermes API server `GET /health` (shallow) — an HTTP liveness probe
  that **never spends an LLM completion** (preserves BR-C11). Deep/protocol health, where
  used, relies on cheap API calls (e.g. `GET /v1/models` or session existence), not chat.
- **`agent ls` queries live on every request** (see NFR-U8-P1): it probes each agent's
  `/health` **in parallel** and reads Docker container status live — **no cached
  `last_health`, no single-snapshot sweep**. The U7 caching/single-snapshot performance model
  is **removed** for the read path.
- The supervisor (U3) still runs periodically for **auto-restart/resiliency**, but the
  `agent ls` read path no longer depends on the supervisor's cache.

### FR-U8-8 — Docker-based provisioning (replaces sbx)
- A new **`DockerProvisioner`** manages agent containers via the `docker` CLI:
  `create/run`, `stop`, `start`, `rm`, `logs`, live container **`status`** (queried in
  real-time per request — **no caching**), and writing the agent's hermes config into the
  container.
- Containers are created with:
  - the built hermes image,
  - `-p 127.0.0.1:<hostPort>:8642` (Q2=A) — host port allocated by caduceus and recorded on
    `AgentRecord`,
  - the agent's env (bearer token, AI-Gateway routing) — secrets passed via env/file, kept
    off the command line where practical,
  - the selected `--runtime` (Q5) — default `runc`, or `runsc` when configured,
  - a durable workspace bind-mount (host-visible agent working dir, as today).
- Outbound routing (agent → caduceus AI-Gateway at the bridge gateway IP `:9701`) is
  preserved; only the **inbound** direction (caduceus → container `:8642`) is new.
- `sbx` and the `sbx template load` image-bridging path are **removed**.

### FR-U8-9 — Image build (docker only)
- The hermes image is built with `docker build` from `images/hermes/Dockerfile` and used
  directly by `docker run` (no `sbx template load`). The Dockerfile installs a hermes
  version that provides `hermes gateway` (the API server), pinned by version/git-ref.

### FR-U8-10 — Optional gVisor runtime (`runsc`)
- Container runtime is configurable: **default `runc`**; **`runsc`** when the user has
  installed gVisor and set the config (Q5).
- When `runsc` is configured but not available/registered with Docker, agent creation (and a
  relevant daemon/`doctor` check) **fails fast with actionable guidance** (Q4=A) — no silent
  fallback to `runc`.
- gVisor is **not** a caduceus dependency; caduceus never installs it.

### FR-U8-11 — `caduceus doctor` command
- New CLI command that reports environment readiness: Docker present/version, hermes image
  present, `runsc` available (and whether it matches the configured runtime), AI-Gateway
  reachability. When gVisor is missing (and desired), it prints install guidance (link +
  steps) but does not install anything. Human default output + `--json`.

### FR-U8-12 — Runtime config surface
- `caduceus gateway config` gains `--runtime runc|runsc` (viewable via `--get`/`--json`),
  persisted to `config.toml` (key `container_runtime`) and also settable via
  `CADUCEUS_CONTAINER_RUNTIME`. Applies to **newly-spawned** containers; existing containers
  keep their runtime until recreated. Validation: value ∈ {`runc`,`runsc`}; light shape check
  only (availability enforced at spawn per FR-U8-10 / Q4).

### FR-U8-13 — Remote agents under the unified transport
- Remote agents remain a **management** distinction only: registered by hermes **API server**
  URL + bearer, lifecycle read-only (no start/stop/rm). They use the same
  `HermesApiTransport`. `register` guidance is updated to describe the API-server URL/token.

### FR-U8-14 — No legacy compatibility (greenfield runtime state)
- The module has **never been deployed** and there are **zero** existing agents. `sbx` is
  removed entirely — **no** migration, **no** legacy-record handling, **no** dual-runtime
  fallback. `AgentRecord` fields specific to the sbx/serve era (e.g. `serve_port`,
  `serve_auth`) are dropped or repurposed for the Docker model (e.g. `host_port`,
  `container_name`) as part of the clean cut; there is no need to read old state.

### FR-U8-15 — Preserve existing U1–U7 behavior & UX
- CLI verbs (`agent create/ls/chat/stop/start/rm/config/logs`, `gateway start/stop/status/
  config`, Web UI), the AI-Gateway, token model, U5 thinking/tool display, U6 hot-apply
  config, and U7 async-create/**warm-up**/boot-reconnect semantics continue to work, now over
  the HTTP/SSE transport and Docker runtime.
- **Exception (intentional simplification):** the U7 fast-`ls` caching/single-snapshot sweep
  is **dropped** — `agent ls` now queries status live per request (FR-U8-7 / NFR-U8-P1).

---

## Non-Functional Requirements

### Performance
- NFR-U8-P1: **Real-time status, no caching (user-directed simplification).** `agent ls`
  queries live on every request — probe each agent's `/health` over HTTP **in parallel** and
  read Docker container status live. The U7 fast-`ls` caching / single-snapshot sweep is
  **removed**. Rationale: HTTP health against a running API server is expected to be fast
  (the old sweep existed to work around slow `sbx`); parallel probing keeps `ls` responsive.
  If this proves slow at higher agent counts, per-agent health caching may be **re-introduced
  later** (explicitly deferred, not part of U8).
- NFR-U8-P2: First-chat warm-up (U7) is preserved: `create` reaches chat-ready (container
  running + `/health` OK + session created) so the first turn has no cold-start stall.
- Performance is **not** a release gate (personal local tool), consistent with prior cycles.

### Security (Best-effort / advisory — Q9)
- NFR-U8-S1: Agent containers publish **only to `127.0.0.1`** (never `0.0.0.0`); the hermes
  API server is not reachable off-host (SECURITY-07 spirit; loopback trust boundary).
- NFR-U8-S2: Every agent's hermes API server requires the bearer token; caduceus sends
  `Authorization: Bearer <token>` on all requests (SECURITY-08).
- NFR-U8-S3: Bearer tokens / secrets are passed via env or 600-perm files, kept off the
  command line where practical, and never logged (SECURITY-03).
- NFR-U8-S4: `runsc` opt-in provides sandbox-escape hardening approaching the prior microVM
  isolation; the default `runc` posture and its trade-off are documented (SECURITY-09/-11).
- NFR-U8-S5: Image/deps pinned (no `latest`) for reproducibility (SECURITY-10) — carries the
  existing pinned hermes version/git-ref.
- NFR-U8-S6: HTTP error handling fails closed and does not leak internal details into chat
  errors (SECURITY-15), reusing the existing `errors` mapping.
- Advisory mode: security findings are **surfaced** in stage completion summaries but are
  **not blocking** for this personal-tool cycle.

### Resiliency (Full — inherited)
- NFR-U8-R1: HTTP/SSE calls use bounded timeouts (connect/read/unary) reusing `Timeouts`;
  streaming has a per-chunk idle timeout.
- NFR-U8-R2: Supervisor health/restart, circuit-breaker, fail-fast-on-unhealthy, and
  boot-reconcile (reconnect running containers on daemon restart) are preserved over the new
  runtime/transport (RESILIENCY-06/-10/-12/-15).
- NFR-U8-R3: `gateway stop` does not tear down agent containers (U7 decoupling preserved);
  boot reconciles from `docker` state.
- NFR-U8-R4: Graceful degradation when Docker or a container is unreachable (clear errors,
  no crash).

### Testability (PBT Full — inherited)
- NFR-U8-T1: PBT for SSE→`ChatEvent` mapping totality + terminal-event invariant under the
  new event set; transport reuse/`is_alive`; runtime-selection validation totality;
  provisioner state machine (stateful PBT analogous to U2/U7).
- NFR-U8-T2: Unit tests use a fake Docker provisioner and a fake hermes API server (HTTP/SSE)
  so the suite runs without Docker; real Docker + hermes API server exercised in Build & Test
  integration (as with prior cycles).

---

## Out of Scope (v1 of U8)
- Interactive tool approval UX (endpoint wired but auto-approve only; Q8=A).
- Automatic migration of sbx-era agents (Q6=A — clean cut).
- Auto-installing gVisor (guidance only; Q3/Q4).
- Multi-node / off-host exposure of agent servers (loopback-only).
- Jobs API, Responses API, fork, and other hermes surfaces not needed for chat/stop/
  approval/history/health.

## Assumptions
- Docker Engine is available on the host (already a prerequisite today); `docker` CLI is on
  PATH. WSL2 loopback publishing works (validated pattern).
- The pinned hermes version exposes `hermes gateway` (API server) with the Sessions + Runs +
  health endpoints; exact endpoint/SSE shapes are confirmed via a **spike** in Functional
  Design / Build & Test (as done for ACP in prior cycles).
- Agent → AI-Gateway outbound over the Docker bridge gateway IP continues to work under plain
  `docker run` (default bridge), as it does today.
- One persistent session per agent remains the model (auto-resume).

## Key Risks
- **Endpoint/SSE shape uncertainty**: hermes API specifics (session vs run composition, SSE
  event names, run-id surfacing for stop) need a spike before final design — mirrors the ACP
  discovery in U3/Build & Test.
- **Trust boundary change**: moving from stdio-exec to an inbound HTTP server adds a network
  surface — mitigated by loopback-only publish + bearer auth (NFR-U8-S1/S2).
- **Cross-cutting blast radius**: touches transport, provisioner, images, health, supervisor,
  daemon wiring, CLI/config, Web UI history — must preserve all current tests + invariants.

## Traceability
- Q1→FR-U8-1/3/4/6, Q2→FR-U8-8, Q3→FR-U8-11, Q4→FR-U8-10, Q5→FR-U8-12,
  Q6→FR-U8-14, Q7→FR-U8-2/13, Q8→FR-U8-5, Q9→NFR Security (advisory) + Resiliency/PBT (full).

## Summary
This cycle re-platforms local agents from `sbx`+ACP(stdio) onto **plain Docker containers**
running the **hermes API server**, with a **single HTTP/SSE transport** for local and remote
agents. It adds an **optional gVisor (`runsc`) runtime** (default `runc`, fail-fast when a
configured `runsc` is unavailable), a **`caduceus doctor`** readiness command, and a
**`gateway config --runtime`** setting. `sbx` is removed entirely — no legacy/migration/
fallback (the module has never been deployed; zero existing agents). U1–U7 behavior/UX and
invariants (terminal-event, warm-up, boot-reconnect, gateway/agent lifecycle decoupling) are
preserved, **except** the U7 fast-`ls` caching/single-snapshot sweep, which is intentionally
dropped in favor of **real-time, no-cache status** (parallel `/health` + live Docker status).
Security Baseline runs in best-effort advisory mode; Resiliency and PBT remain full.
