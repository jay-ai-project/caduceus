# U8 Spike — hermes API Server (empirical findings, hermes 0.17.0)

**Goal**: de-risk the design by confirming the hermes API server surface in the **installed**
version (`Hermes Agent v0.17.0 / 2026.6.19`), since the linked docs track `main` (newer).
Source inspected on-disk at `/home/beom/.hermes/hermes-agent`.

## Headline
The API server exists in 0.17.0 and matches the docs. It is a **platform of the messaging
gateway**, implemented in `gateway/platforms/api_server.py` (`APIServerAdapter`), served over
`aiohttp`. **Launch = `hermes gateway run`** with the API-server platform enabled by env.
> Note the naming clash: the *container-internal* launch verb is `hermes gateway run`. This is
> unrelated to **caduceus gateway** (our daemon). Internal only; no user-facing conflict.

## Launch / enable (confirmed — `gateway/config.py`, `gateway/run.py`)
- Enabled when `API_SERVER_ENABLED` ∈ {true,1,yes} **or** `API_SERVER_KEY` set.
- Env consumed: `API_SERVER_KEY`, `API_SERVER_PORT` (default **8642**, `DEFAULT_PORT`),
  `API_SERVER_HOST`, `API_SERVER_CORS_ORIGINS`, `API_SERVER_MODEL_NAME`.
- `hermes gateway run` runs in the **foreground** (help: "recommended for WSL, Docker, Termux")
  → ideal container entrypoint. Only enabled platforms start (no Telegram/Discord side effects).
- `check_api_server_requirements()` gates on `aiohttp` (bundled with the gateway).

## Auth (confirmed)
- Bearer: `Authorization: Bearer <API_SERVER_KEY>` (`_authenticate`, ~L961-981).
- Server refuses to start without `API_SERVER_KEY`. Invalid key → 401
  `{"error":{"code":"invalid_api_key",...}}`.

## Endpoints (confirmed — `api_server.py` header + routes)
| Capability | Endpoint |
|---|---|
| Chat (stateful, streaming) | `POST /api/sessions/{id}/chat/stream` (SSE) / non-stream `…/chat` |
| Create/list session | `POST /api/sessions` / `GET /api/sessions` |
| Read/patch/delete session | `GET|PATCH|DELETE /api/sessions/{id}` |
| **History** | `GET /api/sessions/{id}/messages` |
| Fork | `POST /api/sessions/{id}/fork` |
| Runs (create→run_id 202) | `POST /v1/runs` |
| Run status / **events (SSE)** | `GET /v1/runs/{id}` / `GET /v1/runs/{id}/events` |
| **Stop** | `POST /v1/runs/{id}/stop` |
| **Approval** | `POST /v1/runs/{id}/approval` |
| OpenAI compat | `POST /v1/chat/completions`, `POST /v1/responses` |
| Discovery | `GET /v1/models`, `GET /v1/capabilities` |
| **Health** | `GET /health`, `GET /v1/health`, `GET /health/detailed` |

## SSE format (confirmed)
`event: <name>\ndata: <json>\n\n` (`await response.write(...)`, `Content-Type: text/event-stream`).

### Session `chat/stream` event vocabulary (L1690-1774)
- `run.started` — **carries `run_id`** (every event does: `payload.setdefault("run_id", run_id)`).
- `message.started` — `{message: {id, role: "assistant"}}`.
- `assistant.delta` — `{message_id, delta}` → **token stream**.
- `tool.progress` — `{message_id, tool_name, delta}`; `tool_name == "_thinking"` for reasoning
  (`reasoning.available` → tool.progress) → **thinking**; other tool_name → tool progress.
- `tool.started` / `tool.completed` / `tool.failed` — `{message_id, tool_name, preview, args}`.
- `assistant.completed` — `{message}` (final assistant content).
- `run.completed` — end-of-run marker.
- `error` — `{message}` (redacted).
- `done` — `{}` → **terminal**.

## Design-affecting confirmations
1. **Stop is wireable from a session turn**: `run_id` is present on the session stream's
   events → `POST /v1/runs/{run_id}/stop`. If cancel is requested before `run.started`, fall
   back to client SSE disconnect.
2. **`/health` is a real HTTP liveness probe** → shallow health with **zero LLM spend**
   (preserves BR-C11). `/health/detailed` or `/v1/models` for deeper checks if needed.
3. Event set is a **superset** of what U5's `ChatEvent` (token/thinking/tool_call/message/
   done/error + `meta`/`ToolCallMeta`) already models → mapping is direct; terminal invariant
   preserved by routing `done`/`run.completed`/`error` through `normalize_stream`.

## Residual items (pin during Code Gen / Build & Test, not blockers)
- Exact JSON shape of `/api/sessions` create response (session id field name) and `/messages`
  payload → confirm live.
- Whether `/health` is auth-exempt (we send Bearer regardless, so non-blocking).
- Dockerfile: swap the `[acp]` extra for the extra that ships the gateway + `aiohttp`; confirm
  `hermes gateway run` present in-image.
- `run.completed` vs `done` ordering (map both defensively; `normalize_stream` guarantees one
  terminal).
