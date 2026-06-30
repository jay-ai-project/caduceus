# U5 Web UI — Code Generation Plan

**Project type**: Brownfield, single Python package at workspace root (`caduceus/`).
**Code location**: workspace root `caduceus/…` + `tests/…`. Docs (summaries) → `aidlc-docs/construction/u5-webui/code/`.
**Principle**: additive / modify-in-place; never break existing 154-test suite or CLI.

## Unit context
- Implements FR-W1…W10. Depends on U2 (AgentView/registry), U3 (transport/events/chat), U4 (control_api/dto). No new runtime dependency (FastAPI `StaticFiles` already available via fastapi; `aiofiles` not needed for StaticFiles in starlette? — verify; if required, add).
- Interfaces/contracts: existing Control API endpoints reused; one new `GET /agents/{name}/history`; chat SSE now additionally carries `thinking`/`tool_call`.

## Steps

### Step 1 — Event model extension (business logic) `caduceus/transport/events.py` [modify]
- [ ] Add `thinking`, `tool_call` to `ChatEventType`. Keep `TERMINAL=(error,done)`.
- [ ] Add `meta: Optional[dict] = None` to `ChatEvent`; `to_dict` includes `meta` only when not None; `from_dict` reads it.
- [ ] Add constructors `thinking_`, `tool_`, `message_(text, role, replay=True)`.
- [ ] `normalize_stream` unchanged (verify still terminal-keyed).

### Step 2 — Event model unit tests `tests/unit/test_chat_events.py` [modify]
- [ ] Round-trip (to_dict/from_dict) for thinking + tool_call incl. populated meta (PBT-W2 seed).
- [ ] thinking/tool_call are non-terminal; normalize_stream passes them through with exactly one terminal.

### Step 3 — Event model PBT `tests/pbt/test_transport_properties.py` [modify]
- [ ] PBT-W1: arbitrary non-terminal sequence (token/thinking/tool_call/message) + optional terminal → normalize_stream emits exactly one terminal, nothing after.

### Step 4 — ACP mapping + history capture `caduceus/transport/acp.py` [modify]
- [ ] In `_prompt`: map `agent_thought_chunk`→`thinking_`, `tool_call`/`tool_call_update`→`tool_` (id=toolCallId, status normalized, input=rawInput, output=content/rawOutput join), truncate 4 KiB, defensive (missing fields → empty; never raise).
- [ ] Add `_norm_status`, `_collect_content`, `_truncate` helpers.
- [ ] Add `load_history(session_id) -> list[HistoryTurn]`: spawn → initialize → session/load capturing replayed `user_message_chunk`/`agent_message_chunk` (coalesce same-role), stop on load response; close; best-effort (any error → []).

### Step 5 — Transport base + remote history `caduceus/transport/base.py` (+ serve.py) [modify]
- [ ] Define `HistoryTurn` (dataclass: role, text) — placed in events.py or base.py.
- [ ] Add `Transport.load_history` default → `[]` (remote/serve inherit no-op).

### Step 6 — ChatService.history `caduceus/transport/chat.py` [modify]
- [ ] `async def history(self, name) -> list[HistoryTurn]`: resolve rec; remote/sessionless/non-local → []; else build a dedicated transport via factory and call `load_history(rec.session_id)`; never raise.

### Step 7 — ACP transport unit tests `tests/unit/test_acp_transport.py` [modify]
- [ ] Fake ACP agent emits thought + tool_call + tool_call_update → asserts mapped ChatEvents (incl. meta, truncation, status normalization).
- [ ] Fake session/load replay → `load_history` returns coalesced turns; failure → [].

### Step 8 — ChatService history unit tests `tests/unit/test_chat_service.py` [modify]
- [ ] history(): remote → []; sessionless → []; local w/ fake transport → turns; transport raises → [].

### Step 9 — Web UI serving module `caduceus/webui/{__init__.py,serve.py}` [create]
- [ ] `mount_webui(app)`: mount `StaticFiles(directory=assets, html=True)` at `/ui`; `GET /` → RedirectResponse `/ui/`. Resolve assets dir via `importlib.resources`/`__file__`.

### Step 10 — Static assets `caduceus/webui/assets/{index.html,styles.css,app.js}` [create]
- [ ] `index.html` — app shell (header, sidebar, main) with `data-testid` on interactive els.
- [ ] `styles.css` — minimal responsive layout, badges, collapsible blocks, light/dark-friendly tokens.
- [ ] `app.js` — single module: polling dashboard, AddAgentModal (local SSE / remote), ChatView (history load + fetch-SSE chat dispatch: token/message/thinking/tool_call/error/done), tool-card upsert by id, confirm-on-remove.

### Step 11 — Control API wiring `caduceus/daemon/control_api.py` [modify]
- [ ] Call `mount_webui(app)` in `build_control_app`.
- [ ] Add `GET /agents/{name}/history` → `{turns:[…]}` from `chat.history(name)`; not-found → `_err`.

### Step 12 — Packaging `pyproject.toml` [modify]
- [ ] Ensure `caduceus/webui/assets/*` ships in the wheel (hatch: `force-include` or `artifacts`/package-data). Add `aiofiles` dependency only if StaticFiles requires it (verify at gen time).

### Step 13 — Control API / webui unit tests `tests/unit/test_control_api.py` (+ `tests/unit/test_webui_serve.py`) [modify/create]
- [ ] `GET /` redirects to `/ui/`; `/ui/` serves index.html (200, text/html).
- [ ] `GET /agents/{name}/history` returns turns from a fake chat service; unknown agent → error.

### Step 14 — Docs `aidlc-docs/construction/u5-webui/code/` [create]
- [ ] `code-summary.md` — files created/modified, endpoints, event-model changes, how to run/verify.
- [ ] Update root `README.md` with a "Web UI" note (`caduceus gateway start` → http://127.0.0.1:9700/).

## Story / requirement traceability
| Step | Requirements |
|---|---|
| 1–3 | FR-W9 (event model), PBT-W1/W2, NFR-W4 |
| 4–8 | FR-W7, FR-W8, FR-W9, FR-W10, BR-W5..W10 |
| 9–13 | FR-W1..W6, BR-W1..W4, BR-W11..W14, NFR-W2/W5 |
| 14 | documentation |

## Quality gates
- Full suite stays green (existing 154 + new). CLI chat unaffected. Terminal invariant holds (PBT). Live browser verification deferred to Build & Test.
