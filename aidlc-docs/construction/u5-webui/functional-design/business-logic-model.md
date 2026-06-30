# U5 Web UI — Business Logic Model

Logic for the Web UI unit. The UI itself is a thin client over **existing** Control
API endpoints; the design-worthy logic is server-side: the **event-model extension**
(L1–L2), **history replay** (L3), and the **web-serving mount** (L4).

## L1 — ChatEvent model extension (pure)
**Where**: `caduceus/transport/events.py`.
- Add enum members `thinking`, `tool_call` to `ChatEventType`. `TERMINAL` stays `(error, done)`.
- Add optional `meta: Optional[dict] = None` to `ChatEvent`; `to_dict` omits `meta` when `None` (stable round-trip; backward-compatible with existing `from_dict`).
- New convenience constructors: `thinking_(text)`, `tool_(title, *, id, name, status, input="", output="")`, and `message_(text, role, replay=True)`.
- `normalize_stream` is **unchanged** — it already keys solely off `is_terminal()`, so the new non-terminal types pass through correctly. (This is the core safety property: PBT-W1.)

## L2 — ACP `session/update` → ChatEvent mapping
**Where**: `caduceus/transport/acp.py` `_prompt` loop (today only `agent_message_chunk` is mapped; everything else is dropped at line ~202).
Map each `session/update.sessionUpdate` variant:
| ACP variant | → ChatEvent |
|---|---|
| `agent_message_chunk` | `token_(text)` *(existing)* |
| `agent_thought_chunk` | `thinking_(text)` |
| `tool_call` | `tool_(title, id=toolCallId, name=title/kind, status=norm(status), input=str(rawInput), output=collect(content/rawOutput))` |
| `tool_call_update` | `tool_(title?, id=toolCallId, status=norm(status), output=collect(content/rawOutput))` |
| `plan`, `available_commands_update`, others | ignored (as today) |
- `norm(status)`: map ACP status strings to `{pending,in_progress,completed,failed}`; unknown → `in_progress`.
- `collect(content)`: join text parts of the ACP `content` array (+ `rawOutput` if present), truncate per BR-W7. Defensive: any missing field → empty string (never raise; a malformed update must not break the stream — BR-W6).
- Terminal handling (`session/prompt` result/error, timeout, EOF, cancel) is **unchanged**.

## L3 — History replay (FR-W10, best-effort, local only)
**Where**: new `ChatService.history(name) -> list[HistoryTurn]` + transport support.
1. Resolve `AgentRecord`. If `kind == remote`, or no `session_id`, or not local → return `[]`.
2. Use a **dedicated short-lived** transport (not the pooled chat transport, to avoid disturbing a live session): `initialize` → `session/load` **with replay capture**.
   - During load, the agent emits `session/update` replay notifications. Capture `user_message_chunk` → turn(role=user), `agent_message_chunk` → turn(role=assistant); coalesce consecutive same-role chunks into one turn. Ignore thought/tool replay (text-only history; BR-W9).
   - Stop when the `session/load` response (matching id) arrives.
3. Close the transport. On **any** failure (load unsupported, stale session, error) → return `[]` (best-effort; BR-W8). Never raise to the UI.
- New abstract `Transport.load_history(session_id) -> list[HistoryTurn]`; `AcpTransport` implements; remote transport returns `[]`.

## L4 — Web UI serving (mount on Control API)
**Where**: new `caduceus/webui/serve.py` `mount_webui(app)`, called from `build_control_app` (U4 `daemon/control_api.py`).
- Mount packaged static assets (`caduceus/webui/assets/`) at `/ui` via `StaticFiles(html=True)` → serves `index.html` at `/ui/`.
- `GET /` → redirect to `/ui/`.
- Assets are part of the wheel (BR-W2 / NFR-W5). No API route is shadowed (UI lives under `/ui`, API under `/agents`,`/status`,…).

## L5 — History endpoint
**Where**: `daemon/control_api.py` new route `GET /agents/{name}/history`.
- Returns JSON `{turns: [{role, text}, …]}` from `ChatService.history(name)`. Bounded, single response (not SSE). Errors → `{turns: []}` (best-effort) or standard `_err` for not-found.

## L6 — Frontend orchestration (vanilla JS, no build)
See `frontend-components.md`. Key flows:
- **Dashboard poll**: every `POLL_MS` (default 3000) GET `/status` + `/agents`; re-render; pause polling while a modal/chat SSE is active is **not** required (polling is cheap), but in-flight provisioning shows live SSE separately.
- **Add local**: POST `/agents` (SSE) → render phases live → on `done` refresh list; on `error` show message.
- **Add remote**: POST `/agents/register` → show guidance → refresh list.
- **Chat open**: GET `/agents/{name}/history` → render past turns → then live.
- **Chat send**: POST `/agents/{name}/chat` (SSE via `fetch` + ReadableStream); dispatch by event type:
  - `token`/`message` → append to current assistant bubble
  - `thinking` → append to a collapsible "thinking" block for the in-progress turn
  - `tool_call` → upsert a collapsible tool card keyed by `meta.id` (name/status/input/output)
  - `error` → error bubble, end turn
  - `done` → finalize turn

## Resiliency behaviors (inherited, applicable)
- Daemon-not-running / agent-unavailable / SSE disconnect surface as clear UI states, never a hang (NFR-W3). Chat errors arrive in-band as terminal `error` events.
- Lifecycle/health badges reflect server truth on each poll; remote start/stop disabled (BR-A10 inherited).

## PBT targets (full, inherited)
- **PBT-W1** (invariant): for any sequence of arbitrary non-terminal events (`token`/`thinking`/`tool_call`/`message`) optionally followed by a terminal, `normalize_stream` yields exactly one terminal and emits nothing after it — i.e., the extension does not break the U3 terminal-event property.
- **PBT-W2** (round-trip): `ChatEvent.from_dict(ev.to_dict()) == ev` for all extended types incl. populated `meta`.
