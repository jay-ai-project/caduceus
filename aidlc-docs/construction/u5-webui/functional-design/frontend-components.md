# U5 Web UI — Frontend Components

**Stack**: vanilla HTML/CSS/JS, **no build step** (Q1=A). Single-page app served at
`/ui/`. No external CDN/runtime dependency at load (offline-capable local tool).
State is in-memory only (no persistence; transcripts are ephemeral — Q5/requirements).

## File layout (packaged static assets)
```
caduceus/webui/
├── __init__.py
├── serve.py            # mount_webui(app): StaticFiles(/ui) + GET / redirect
└── assets/
    ├── index.html      # app shell
    ├── styles.css      # minimal layout + light/dark-friendly tokens
    └── app.js          # all client logic (single module)
```

## Layout / component hierarchy
```
App
├── Header            — gateway status (running, listeners, upstream, version, agent count)
├── Sidebar (Dashboard)
│   ├── [+ Add Agent] button → AddAgentModal
│   └── AgentList
│       └── AgentCard × N   — name, kind badge, lifecycle badge, health badge,
│                             endpoint/connection, model; actions: Chat, Stop/Start, Remove
└── Main
    └── ChatView (for the selected agent)  — empty-state until an agent is chosen
        ├── TranscriptList
        │   └── MessageBubble (user | assistant)
        │       ├── ThinkingBlock (collapsible)   — assistant turns only
        │       └── ToolCallCard × N (collapsible) — name · status · input · output
        └── Composer  — textarea + Send (Enter to send, Shift+Enter newline)
```

## Component contracts

### AgentCard
- **Props**: AgentView (name, kind, lifecycle, health, endpoint, model_alias, has_session).
- **Badges**: lifecycle (creating=amber, running=green, stopped=grey, failed=red); health (healthy/degraded/unhealthy/unknown).
- **Actions**: `Chat` (open ChatView); `Stop`/`Start` (POST stop|start; **disabled for remote** — BR-W11); `Remove` (confirm → DELETE — BR-W12). Refresh list after any action.

### AddAgentModal
- **Tabs**: `Local` | `Remote`.
- **Local form**: name (required), model (optional), upstream_url (optional), image (optional).
  - Submit → POST `/agents` and read SSE; render a **live progress log** of `progress` phases; on `done` close + refresh; on `error` show message inline.
- **Remote form**: name (required), endpoint URL (required), auth (optional).
  - Submit → POST `/agents/register`; show returned `guidance` text; refresh.
- **Validation**: name non-empty; endpoint looks like a URL (`http(s)://…`). (BR-W14: explicit success/error.)

### ChatView
- **On open(agentName)**: clear transcript → `GET /agents/{name}/history` → render returned turns (text-only) → focus composer.
- **On send(message)**:
  1. Append a user MessageBubble.
  2. Open assistant MessageBubble (in-progress).
  3. POST `/agents/{name}/chat` via `fetch`, read the response body as a stream, parse SSE `data:` lines into ChatEvent, dispatch:
     - `token` / `message` → append text to the assistant bubble.
     - `thinking` → append to the bubble's ThinkingBlock (auto-created, collapsed by default with a live "thinking…" hint while streaming).
     - `tool_call` → upsert a ToolCallCard keyed by `meta.id`: show `name`, `status` badge, and collapsible `input`/`output`. Updates merge into the same card.
     - `error` → mark the assistant bubble as errored, show `data`; end turn.
     - `done` → finalize the bubble (collapse thinking; stop spinner).
  - Composer disabled while a turn is streaming; a `Stop` affordance may cancel by aborting the fetch (server cancels cooperatively).

### Header / polling
- Poll `GET /status` + `GET /agents` every `POLL_MS` (default 3000). On fetch failure → header shows "daemon unreachable", list dimmed (BR-W13).

## User interaction flows
1. **View dashboard** → cards auto-refresh; provisioning agents show `creating` until healthy.
2. **Add local agent** → modal → live phases → card appears `running`.
3. **Add remote agent** → modal → guidance shown → card appears.
4. **Chat** → pick agent → history loads → type → streamed answer with inline thinking + tool cards.
5. **Manage** → stop/start/remove from card (remote stop/start disabled).

## Form validation rules
- Local: `name` required, trimmed, non-empty.
- Remote: `name` required; `endpoint` required and must start with `http://`/`https://`.
- Remove: confirm dialog before issuing DELETE.

## API integration points (all existing except history)
| UI action | Endpoint |
|---|---|
| Dashboard poll | `GET /status`, `GET /agents` |
| Add local | `POST /agents` (SSE) |
| Add remote | `POST /agents/register` |
| Stop / Start | `POST /agents/{name}/stop` / `/start` |
| Remove | `DELETE /agents/{name}` |
| Chat history | `GET /agents/{name}/history`  *(NEW — L5)* |
| Chat stream | `POST /agents/{name}/chat` (SSE; now also emits `thinking`/`tool_call`) |

## Out of scope (v1 UI)
- Config editing and logs viewer (endpoints exist; not surfaced now — Q9 blank).
- Auth, theming switcher (CSS is theme-friendly but no toggle required), remote history.
