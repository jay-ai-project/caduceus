# U5 Web UI — Domain Entities

Technology-agnostic entities for the Web UI unit. Most data entities are **reused
from U2/U3/U4** (secret-free projections); U5 adds only the chat **event-model
extension** and a thin **history transcript** entity.

## Reused (unchanged) entities
- **AgentView** (U4 `common/dto.py`) — secret-free agent projection (name, kind, lifecycle, health, endpoint, model_alias, has_session, created_at). Source for the dashboard.
- **GatewayStatus** (U4) — daemon status projection (running, pid, listeners, upstream, agent_count, version).
- **CreateSpec / RegisterSpec** (U4) — agent-add request shapes.
- **ProvisioningProgress** — the existing `POST /agents` SSE event stream (`{event: progress|done|error, phase, detail, agent}`).

## Extended entity — ChatEvent (U3 `transport/events.py`)
The uniform streaming token. **Additive** extension — existing fields/behavior unchanged.

| Field | Type | Notes |
|---|---|---|
| `type` | ChatEventType | **enum extended** (below) |
| `data` | str | text payload (token text / thinking text / human tool title / message text) |
| `code` | Optional[str] | machine code on terminals (unchanged) |
| `meta` | Optional[dict] | **NEW** — structured payload for `tool_call` and replayed `message` events; `None`/omitted otherwise |

### ChatEventType (extended)
| Value | Terminal? | Meaning | `data` | `meta` |
|---|---|---|---|---|
| `token` | no | assistant output chunk (existing) | text | — |
| `message` | no | a whole message (existing; **also used for replayed history turns**) | text | `{role: "user"\|"assistant", replay: true}` (history only) |
| `thinking` | **no (NEW)** | incremental reasoning/thought chunk | thought text | — |
| `tool_call` | **no (NEW)** | a tool invocation start **or** update | human title | `ToolCallMeta` (below) |
| `error` | yes | terminal failure (existing) | message | — |
| `done` | yes | terminal normal/cancel end (existing) | reason | — |

**Invariant preserved**: only `error`/`done` are terminal. `thinking` and `tool_call`
are non-terminal and flow through `normalize_stream` exactly like `token` (zero-or-more
before the single terminal). This is the property PBT must protect.

### ToolCallMeta (the `meta` dict for `tool_call`)
| Key | Type | Notes |
|---|---|---|
| `id` | str | tool call id (`toolCallId`) — client merges start+updates by this key |
| `name` | str | tool name / `title` / `kind` |
| `status` | str | `pending` \| `in_progress` \| `completed` \| `failed` (normalized from ACP) |
| `input` | str | best-effort stringified args (`rawInput`); may be truncated |
| `output` | str | best-effort stringified result (`rawOutput`/`content`); may be truncated |

Truncation cap: **BR-W7** (default 4 KiB per field) to keep SSE frames small.

## New entity — HistoryTranscript (FR-W10)
A bounded, best-effort list of prior turns for an agent's persisted session.

| Field | Type | Notes |
|---|---|---|
| `turns` | list[HistoryTurn] | ordered oldest→newest |

**HistoryTurn**: `{role: "user"|"assistant", text: str}`. Derived from the ACP
`session/load` replay (user_message_chunk / agent_message_chunk). Past thinking/tool
events are **not** reconstructed into history (kept text-only; BR-W9).

## Relationships
```
Dashboard ──polls──> [AgentView…] + GatewayStatus
ChatView  ──GET────> HistoryTranscript (once, on open)
ChatView  ──SSE────> ChatEvent stream (token|thinking|tool_call|message|error|done)
AddAgent  ──SSE────> ProvisioningProgress  (local)
AddAgent  ──POST───> AgentView + guidance   (remote)
```
