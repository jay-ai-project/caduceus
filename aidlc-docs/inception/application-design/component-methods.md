# Component Methods — Caduceus

Method signatures and I/O at interface level (Python-flavored, `async` where I/O-bound). **Business rules and validation details are deferred to Functional Design (per-unit).** Types referenced here are defined in Functional Design; informal shapes are given inline.

Common types (informal):
- `AgentRecord`: `{ name, kind: "local"|"remote", sbx_id?, endpoint, serve_port?, session_id?, model?, upstream_url?, status, created_at }`
- `HealthStatus`: `{ level: "healthy"|"degraded"|"unhealthy", shallow: bool, deep: bool, detail, checked_at }`
- `ChatEvent`: `{ type: "token"|"message"|"error"|"done", data }`
- `ConfigSnapshot` / `ConfigChange`: skills[], tools{enabled[],disabled[]}, soul(str), core{key:value}

---

## C1. CLI (typer commands → ControlAPIClient calls)
- `agent_create(name: str, model: str|None, upstream_url: str|None, image: str|None) -> int`
- `agent_register(name: str, endpoint: str, auth: str|None) -> int`
- `agent_ls(json: bool, deep: bool) -> int`
- `agent_chat(name: str, query: str|None) -> int`  *(interactive if query is None)*
- `agent_config(name: str, get: bool, set_kv: list[str], add_skill: list[str], soul_file: str|None, enable_tool/disable_tool: list[str]) -> int`
- `agent_logs(name: str, follow: bool) -> int`
- `agent_stop(name)/agent_start(name)/agent_rm(name, force: bool) -> int`
- `gateway_start(foreground: bool)/gateway_stop()/gateway_status(json: bool) -> int`

## C2. ControlAPIClient
- `create_agent(spec: CreateSpec) -> AgentRecord`
- `register_agent(spec: RegisterSpec) -> AgentRecord`
- `list_agents(deep: bool) -> list[AgentView]`
- `remove_agent(name, force) -> None`
- `stop_agent(name)/start_agent(name) -> AgentRecord`
- `chat(name, message) -> AsyncIterator[ChatEvent]`  *(SSE)*
- `get_config(name) -> ConfigSnapshot` · `set_config(name, change: ConfigChange) -> ConfigResult`
- `logs(name, follow) -> AsyncIterator[str]`  *(SSE)*
- `status() -> GatewayStatus` · `is_daemon_up(timeout) -> bool`

## C3. Daemon / GatewayService
- `start(foreground: bool) -> None`  *(acquire lock/PID, build apps, run uvicorn for both listeners, start Supervisor)*
- `stop() -> None`  *(graceful: stop Supervisor, drain, release lock)*
- `status() -> GatewayStatus`  *(pid, uptime, listeners, upstream health, agent count)*
- `build_app() -> tuple[FastAPI(control), FastAPI(aigateway)]`

## C4. ControlAPI (routes → services)
- `POST /agents (CreateSpec) -> AgentRecord`
- `POST /agents/register (RegisterSpec) -> AgentRecord`
- `GET /agents?deep= -> list[AgentView]`
- `DELETE /agents/{name}?force= -> 204`
- `POST /agents/{name}/stop|start -> AgentRecord`
- `POST /agents/{name}/chat ("{message}") -> text/event-stream(ChatEvent)`
- `GET /agents/{name}/config -> ConfigSnapshot` · `PUT /agents/{name}/config (ConfigChange) -> ConfigResult`
- `GET /agents/{name}/logs?follow= -> text/event-stream(str)`
- `GET /healthz -> {ok}` · `GET /status -> GatewayStatus`

## C5. AIGateway (OpenAI-compatible; bind host-gateway iface)
- `POST /v1/chat/completions (OpenAIChatRequest, agent_id from header/api-key/path) -> SSE | OpenAIChatResponse`
- `GET /v1/models -> OpenAIModelList`

## C6. AgentService
- `create(spec: CreateSpec) -> AgentRecord`
- `register(spec: RegisterSpec) -> AgentRecord`
- `list(deep: bool) -> list[AgentView]`  *(joins Registry + HealthChecker)*
- `remove(name: str, force: bool) -> None`
- `stop(name)/start(name) -> AgentRecord`
- `_provision_local(spec) -> AgentRecord`  *(ImageBuilder→Provisioner→configure→serve→verify)*

## C7. ChatService
- `chat_stream(name: str, message: str) -> AsyncIterator[ChatEvent]`
- `_ensure_session(rec: AgentRecord) -> str`  *(create-or-resume; persist session_id)*

## C8. ConfigService
- `get_config(name: str) -> ConfigSnapshot`
- `set_config(name: str, change: ConfigChange) -> ConfigResult`  *(local only; remote → ReadOnlyError)*

## C9. AIGatewayService
- `complete(request: OpenAIChatRequest, agent_id: str|None) -> AsyncIterator[bytes] | OpenAIChatResponse`
- `list_models() -> OpenAIModelList`
- `_resolve_route(agent_id) -> Route{upstream_url, model}`  *(default; per-agent override v2)*

## C10. Registry / StateStore
- `load() -> State` · `save(state: State) -> None`  *(atomic: write temp + os.replace)*
- `get(name) -> AgentRecord|None` · `list() -> list[AgentRecord]`
- `upsert(rec: AgentRecord) -> None` · `delete(name) -> None`
- `set_session(name, session_id) -> None`

## C11. Provisioner (sbx adapter)
- `create_sandbox(name, image, env: dict) -> SbxInfo`
- `publish_port(name, sandbox_port) -> host_port: int`
- `exec(name, argv: list[str], input: str|None, timeout) -> ExecResult`
- `cp_to(name, src, dst) / cp_from(name, dst, src) -> None`
- `start(name)/stop(name)/remove(name) -> None`
- `status(name) -> SbxStatus`  *(via `sbx ls --json`)*
- `logs(name, follow) -> AsyncIterator[str]`
- `configure_hermes(name, aigateway_url, model) -> None`  *(hermes config set / custom_providers)*
- `start_serve(name) -> serve_port: int`  *(launch `hermes serve`, publish port)*

## C12. ImageBuilder
- `ensure_image(tag: str = DEFAULT) -> ImageRef`  *(build from bundled Dockerfile if missing/stale)*
- `image_exists(tag) -> bool`

## C13. Transport (abstract) / ServeTransport
- `async open() -> None` · `async close() -> None`
- `async chat_stream(session_id: str|None, message: str) -> AsyncIterator[ChatEvent]`
- `async health() -> HealthStatus`
- `async get_config() -> ConfigSnapshot` *(optional; may be unsupported → NotSupported)*
- `async set_config(change) -> ConfigResult` *(optional)*
- factory: `Transport.for_agent(rec: AgentRecord) -> Transport`

## C14. UpstreamClient
- `async complete(request: OpenAIChatRequest, target: Route) -> AsyncIterator[bytes] | OpenAIChatResponse`
- `async models(target: Route) -> OpenAIModelList`

## C15. HealthChecker
- `async check(name: str, deep: bool=False) -> HealthStatus`
- `async check_upstream() -> HealthStatus`

## C16. ConfigEditor
- `async read(name) -> ConfigSnapshot`
- `async apply(name, change: ConfigChange) -> ConfigResult`  *(skills/tools/soul/core via Provisioner.exec/cp; restart serve if needed)*

## C17. Supervisor
- `start() -> None` · `stop() -> None`
- `async _sweep() -> None`  *(health sweep, reconnect, restart, back-off/circuit-break)*

## C18. Config
- `load() -> Settings`  *(env > file > defaults; upstream_url, default_model, control_bind, aigateway_bind, state_dir, timeouts)*

## C19. Logging
- `get_logger(name) -> Logger` *(structured, secret-redacting)*
- `async agent_logs(name, follow) -> AsyncIterator[str]`

---

## PBT property hooks (for Functional Design / PBT-01)
- **Registry**: `save→load` round-trip identity (PBT-02); `upsert/delete` state-machine invariants (PBT-06).
- **AIGatewayService**: request/response mapping invariants; route resolution defaults (PBT-03).
- **Name validation**: idempotent/normalized agent names (PBT-03/04).
- **Config rewrite**: provider base_url for local agents always equals the AI-Gateway URL (invariant, PBT-03).
