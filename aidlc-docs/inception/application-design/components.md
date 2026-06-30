# Components — Caduceus

High-level component identification, responsibilities, and interfaces. Detailed business rules are deferred to Functional Design (per-unit, CONSTRUCTION).

**Confirmed design decisions** (Application Design Q1–Q4):
- CLI↔daemon = loopback HTTP (FastAPI).
- State store = single JSON file with atomic writes.
- Listeners split: **Control API** binds 127.0.0.1 only; **AI-Gateway** binds a container-reachable interface (`host.docker.internal` / Docker host-gateway).
- Session ownership = **hermes** owns the session store; caduceus persists only the per-agent session id/name.

**Process model**: one `caduceus` **daemon** + a thin **CLI** client.

---

## Layered view

```
  CLI  --HTTP(loopback)-->  Control API  -->  Domain Services  -->  Adapters
                                                   |                   |
                           AI-Gateway (host-gw) ---+                   +--> sbx/docker, hermes serve, upstream LLM, JSON state
```

Text alternative: The CLI calls the Control API over loopback HTTP. The Control API and the AI-Gateway both invoke domain services (AgentService, ChatService, ConfigService, AIGatewayService). Domain services use adapters (Registry/StateStore, Provisioner, ImageBuilder, Transport/ServeTransport, UpstreamClient, HealthChecker, ConfigEditor, Supervisor) that talk to sbx/docker, hermes serve endpoints, the upstream LLM, and the JSON state file.

---

## C1. CLI  *(Unit U4)*
- **Purpose**: User-facing `caduceus` command (typer). Parses `agent` and `gateway` subcommands; renders human-readable and `--json` output; displays streaming chat.
- **Responsibilities**: argument parsing/validation; call ControlAPIClient; render results/errors; interactive chat loop (read input, stream tokens); start daemon transparently if not running (for non-gateway commands) or instruct user.
- **Interface (consumed by user)**: `caduceus agent create|register|ls|chat|config|logs|stop|start|rm`, `caduceus gateway start|stop|status`.
- **Criticality**: Medium (replaceable thin client).

## C2. ControlAPIClient  *(U4)*
- **Purpose**: HTTP client (httpx) wrapping the daemon Control API for the CLI.
- **Responsibilities**: request/response (JSON); consume SSE streams (chat tokens, log tail); map HTTP errors to CLI errors; short connect timeout to detect a down daemon.
- **Interface**: typed methods mirroring Control API endpoints (see component-methods.md).
- **Criticality**: Medium.

## C3. Daemon / GatewayService  *(U4)*
- **Purpose**: The long-lived caduceus process; lifecycle and composition root.
- **Responsibilities**: `start/stop/status`; PID file + single-instance lock; construct and host the two FastAPI apps (Control API on 127.0.0.1, AI-Gateway on host-gateway iface); own singletons (Registry, Provisioner, Transports, Supervisor, Config, Logging); graceful shutdown.
- **Interface**: process control (CLI `gateway *`) + internal wiring.
- **Criticality**: **High** (hub).

## C4. ControlAPI  *(U4)*
- **Purpose**: FastAPI app (bind 127.0.0.1) exposing the daemon's control surface to the CLI.
- **Responsibilities**: HTTP routes → domain services; request validation (pydantic); SSE for chat/logs streaming; uniform error envelope; `--json`-friendly payloads.
- **Interface**: `POST /agents`, `POST /agents/register`, `GET /agents`, `DELETE /agents/{name}`, `POST /agents/{name}/(stop|start)`, `POST /agents/{name}/chat` (SSE), `GET/PUT /agents/{name}/config`, `GET /agents/{name}/logs` (SSE), `GET /healthz`, `GET /status`.
- **Criticality**: High.

## C5. AIGateway  *(U1)*
- **Purpose**: OpenAI-compatible LLM proxy the agents call instead of the LLM directly. Binds a container-reachable interface.
- **Responsibilities**: implement `POST /v1/chat/completions` (streaming SSE + non-stream) and `GET /v1/models`; identify the calling agent (path/header/api-key) for routing; delegate to AIGatewayService; pass-through streaming.
- **Interface**: OpenAI REST (`/v1/*`).
- **Criticality**: **High** (all inference flows through it).

## C6. AgentService  *(U2)*
- **Purpose**: Orchestrate agent lifecycle.
- **Responsibilities**: `create` (ImageBuilder→Provisioner→configure hermes→start serve→Registry→verify), `register` (validate endpoint→Registry), `list` (Registry + HealthChecker), `remove` (Provisioner teardown for local / de-register for remote), `stop/start` (Provisioner; error for remote).
- **Interface**: see component-methods.md.
- **Criticality**: High.

## C7. ChatService  *(U3)*
- **Purpose**: Orchestrate streaming chat with session continuity.
- **Responsibilities**: resolve agent → Transport; ensure/track session id via Registry (hermes owns the actual session, per Q4=A); stream tokens to caller; handle agent-down with graceful error; record session id on first turn.
- **Interface**: `chat_stream(name, message) -> AsyncIterator[ChatEvent]`.
- **Criticality**: High.

## C8. ConfigService  *(U4)*
- **Purpose**: Orchestrate agent configuration read/edit.
- **Responsibilities**: read config (local + remote); edit skills/soul/tools/core (local only via ConfigEditor; remote → clear "read-only" error); trigger hermes reload/restart when needed.
- **Interface**: `get_config(name)`, `set_config(name, change)`.
- **Criticality**: Medium.

## C9. AIGatewayService  *(U1)*
- **Purpose**: Proxy/routing logic behind AIGateway.
- **Responsibilities**: resolve routing target for the calling agent (default upstream + default model; per-agent model/url override is **designed-for, v2**); translate/forward OpenAI requests via UpstreamClient; stream responses back; enforce timeouts; map errors to OpenAI error shape.
- **Interface**: `complete(request, agent_id) -> AsyncIterator[bytes] | Response`, `list_models() -> ModelList`.
- **Criticality**: High.

## C10. Registry / StateStore  *(U2)*
- **Purpose**: Durable local state (Q2=A: single JSON file, atomic writes).
- **Responsibilities**: persist `AgentRecord`s (name, kind local/remote, sbx id, endpoint, ports, session id, settings, status cache); CRUD; atomic write (temp file + rename); in-process lock to serialize access; schema version for migration.
- **Interface**: `get/list/upsert/delete`, `load/save`.
- **Criticality**: High (loss → re-create/re-register; RES-2/RES-7).

## C11. Provisioner (sbx adapter)  *(U2)*
- **Purpose**: All `sbx`/`docker` interactions for managed (local) agents.
- **Responsibilities**: create sandbox from hermes image (`sbx create shell -t <image> --name <n>`); publish hermes serve port to loopback (`sbx ports`); `exec`/`cp` to configure hermes (provider base_url→AIGateway, default model) and start `hermes serve`; `stop/start/rm`; fetch logs; status via `sbx ls --json`.
- **Interface**: see component-methods.md.
- **Criticality**: High.

## C12. ImageBuilder  *(U2)*
- **Purpose**: Build/ensure the hermes-preinstalled Docker image (Q4-image=A: authored Dockerfile).
- **Responsibilities**: build & tag from the bundled Dockerfile; idempotent (skip if present + version match); surface build errors.
- **Interface**: `ensure_image(tag) -> ImageRef`.
- **Criticality**: Medium (one-time/bootstrap).

## C13. Transport (interface) + ServeTransport (impl)  *(U3)*
- **Purpose**: Common, streaming-capable channel to an agent's hermes, regardless of local/remote (serve-first; ACP later).
- **Responsibilities** (interface): `chat_stream`, `health`, optional `get_config`/`set_config`, `open/close`, `session` handling. **ServeTransport** implements via `hermes serve` JSON-RPC/WebSocket (local published port or remote URL) with auth + reconnect.
- **Interface**: abstract `Transport` (see component-methods.md). Future `AcpTransport` behind same interface.
- **Criticality**: High.

## C14. UpstreamClient  *(U1)*
- **Purpose**: OpenAI-compatible client to the real LLM upstream (default Ollama `localhost:11434/v1`).
- **Responsibilities**: forward chat/completions with streaming pass-through; explicit timeouts; surface upstream errors; (v2) target overridable per agent.
- **Interface**: `complete(request) -> stream/Response`, `models() -> ModelList`.
- **Criticality**: High.

## C15. HealthChecker  *(U2/U3)*
- **Purpose**: Determine agent and upstream health.
- **Responsibilities**: **shallow** (transport endpoint / sbx running) and **deep** (hermes responsive via Transport.health + upstream reachable via UpstreamClient) checks; cache last status + timestamp; feed `ls` and Supervisor.
- **Interface**: `check(name, deep=False) -> HealthStatus`, `check_upstream() -> HealthStatus`.
- **Criticality**: Medium (RES-3 / RESILIENCY-06).

## C16. ConfigEditor  *(U4)*
- **Purpose**: Apply config edits to a **local** agent.
- **Responsibilities**: edit skills (`hermes skills ...` via exec), tools (`hermes tools enable/disable`), soul (`SOUL.md` via cp), core config (`hermes config set`); validate; restart hermes serve if required.
- **Interface**: `apply(name, change) -> ConfigResult`, `read(name) -> ConfigSnapshot`.
- **Criticality**: Medium.

## C17. Supervisor  *(U3)*
- **Purpose**: Background resiliency (RES-4/RES-5).
- **Responsibilities**: periodic health sweep; reconnect dropped transports; restart a managed agent's hermes serve where feasible; mark agents unhealthy + circuit-break repeatedly failing ones (back-off); never let one agent failure crash the daemon.
- **Interface**: `start()/stop()`, internal loop.
- **Criticality**: Medium-High.

## C18. Config (caduceus settings)  *(cross-cutting)*
- **Purpose**: caduceus's own configuration.
- **Responsibilities**: resolve upstream URL (default `http://localhost:11434/v1`), default model (`your-model`), listener ports/binds, paths (state dir `~/.caduceus/`), timeouts; precedence env > config file > defaults.
- **Interface**: `load() -> Settings`.
- **Criticality**: Medium.

## C19. Logging  *(cross-cutting, U4)*
- **Purpose**: Structured logging + per-agent log access (RES-6 / RESILIENCY-05).
- **Responsibilities**: structured daemon logs (no secrets); expose agent hermes logs via Provisioner (local).
- **Interface**: standard logger + `agent_logs(name, follow)`.
- **Criticality**: Medium.

---

## Criticality summary (RESILIENCY-01)
| Criticality | Components |
|---|---|
| High | Daemon/GatewayService, ControlAPI, AIGateway, AgentService, ChatService, AIGatewayService, Registry, Provisioner, Transport/ServeTransport, UpstreamClient |
| Medium-High | Supervisor |
| Medium | CLI, ControlAPIClient, ConfigService, ImageBuilder, HealthChecker, ConfigEditor, Config, Logging |

External dependencies: Docker daemon, `sbx` CLI, `hermes` (inside image / remote), upstream LLM (Ollama).
