# U5 Web UI — Code Summary

## Files

### Created
- `caduceus/webui/__init__.py` — exports `mount_webui`.
- `caduceus/webui/serve.py` — `mount_webui(app)`: mounts the SPA at `/ui` (StaticFiles, html=True) + `GET /`→`/ui/` redirect.
- `caduceus/webui/assets/index.html` — app shell (topbar status, sidebar dashboard, chat view, add-agent modal). `data-testid` on interactive elements.
- `caduceus/webui/assets/styles.css` — minimal layout, badges, collapsible thinking/tool cards, light/dark via `prefers-color-scheme`.
- `caduceus/webui/assets/app.js` — vanilla SPA: polling dashboard, add-agent (local SSE / remote), chat (fetch-SSE) with token/thinking/tool_call/error/done dispatch, tool-card upsert by id, confirm-on-remove.

### Modified
- `caduceus/transport/events.py` — `ChatEventType` += `thinking`, `tool_call`; `ChatEvent.meta` (optional, omitted when None); constructors `thinking_`/`tool_`/`message_`; new `HistoryTurn` dataclass. `normalize_stream` unchanged.
- `caduceus/transport/acp.py` — `_map_update` maps ACP `session/update` (`agent_message_chunk`→token, `agent_thought_chunk`→thinking, `tool_call`/`tool_call_update`→tool_call), defensive (`BR-W6`), 4 KiB truncation (`BR-W7`), status normalization. New `load_history`/`_replay_load` capturing the `session/load` replay.
- `caduceus/transport/base.py` — `Transport.load_history` default `[]` (remote/serve no-op).
- `caduceus/transport/chat.py` — `ChatService.history(name)` (best-effort, local-only, dedicated short-lived transport; `BR-W8/W9/W10`).
- `caduceus/daemon/control_api.py` — `mount_webui(app)`; new `GET /agents/{name}/history` → `{turns:[…]}`.
- `pyproject.toml` — note that `packages=["caduceus"]` already ships assets (no extra config).
- Tests: `tests/unit/test_chat_events.py`, `tests/unit/test_acp_transport.py`, `tests/unit/test_chat_service.py`, `tests/unit/test_control_api.py`, `tests/pbt/test_transport_properties.py`; `tests/fakes.py` (FakeTransport.load_history, FakeChatService.history).

## Endpoints (UI surface)
| Method | Path | Use |
|---|---|---|
| GET | `/` | redirect → `/ui/` |
| GET | `/ui/…` | static SPA |
| GET | `/status`, `/agents` | dashboard poll (existing) |
| POST | `/agents` (SSE) | local provision w/ live progress (existing) |
| POST | `/agents/register` | remote register (existing) |
| POST | `/agents/{n}/stop|start`, DELETE `/agents/{n}` | lifecycle (existing) |
| GET | `/agents/{n}/history` | **new** — best-effort prior turns |
| POST | `/agents/{n}/chat` (SSE) | streaming chat; now also emits `thinking`/`tool_call` |

## Tests
- `173 passed` (was 154; +19): event-model round-trip/non-terminal (Step 2), PBT-W1 terminal-invariant w/ thinking+tool + PBT-W2 meta round-trip (Step 3), ACP thinking/tool mapping + malformed-safe + history replay (Step 7), ChatService.history matrix (Step 8), `/` redirect + `/ui/` index + history endpoint (Step 13).
- Wheel build verified to include `caduceus/webui/assets/{index.html,styles.css,app.js}`.

## How to run / verify
1. `caduceus gateway start` (foreground) — daemon serves Control API on `127.0.0.1:9700`.
2. Open `http://127.0.0.1:9700/` → redirects to the Web UI.
3. Dashboard lists agents (polls every 3 s); **+ Add** to provision a local sandbox (live phases) or register a remote endpoint.
4. Click an agent → **Chat**: prior history loads (best-effort), then stream a turn — thinking shows in a collapsible block, tool calls as collapsible cards (name/status/input/output).

Live browser end-to-end verification against a real local sbx hermes agent is performed in **Build & Test**.
