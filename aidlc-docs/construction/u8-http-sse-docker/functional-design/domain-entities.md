# U8 Functional Design — Domain Entities

Technology-agnostic entities for the HTTP/SSE + Docker migration. Reuses existing models
where possible; changes are additive/renaming behind stable ports.

## AgentRecord (reshaped — clean cut, FR-U8-14)
Existing `AgentRecord` with sbx/serve-era fields **removed** and Docker/API fields **added**.
No legacy state to read (module never deployed).

| Field | Change | Meaning |
|---|---|---|
| `name` | keep | logical agent name |
| `kind` | keep | `local` (caduceus-managed container) \| `remote` (registered URL) |
| `token` | keep | shared secret: caduceus→agent Bearer **and** in-container `API_SERVER_KEY` |
| `endpoint` | keep, now **also for local** | base URL of the hermes API server (local: `http://127.0.0.1:<host_port>`; remote: user URL) |
| `container_name` | **rename** from `sandbox_name` | Docker container name (`cad-<name>`) |
| `host_port` | **new** (replaces `serve_port`) | published host loopback port → `endpoint` |
| `workspace_path` | keep | host dir bind-mounted into the container |
| `runtime` | **new** | container runtime used at spawn (`runc`\|`runsc`); informational/reconcile |
| `model_alias` | keep | `default` sentinel routed by AI-Gateway |
| `session_id` | keep | persistent hermes session id (auto-created/resumed) |
| `lifecycle` | keep | `creating`\|`running`\|`stopped`\|`failed`\|`registered` |
| `last_health` | keep | last `HealthStatus` (supervisor-updated; **not** used by `ls`) |
| ~~`serve_port`~~ | **drop** | (serve era) |
| ~~`serve_auth`~~ | **drop** | (serve era) |

## ContainerRuntime (new enum / value)
- Values: `runc` (default), `runsc` (gVisor, opt-in).
- Held in `Settings.container_runtime`; validated ∈ {runc, runsc} (light shape check).
- Availability enforced **at spawn** (fail-fast), not at config-set time (BR-R2).

## HermesApiEndpoint (conceptual — the transport's target)
A reachable hermes API server: `base_url` + `bearer`. Uniform for local & remote (Q7).
- Chat (stateful): `POST {base}/api/sessions/{sid}/chat/stream` (SSE)
- Session mgmt: `POST {base}/api/sessions`, `GET {base}/api/sessions/{sid}/messages`
- Stop: `POST {base}/v1/runs/{run_id}/stop`
- Approval: `POST {base}/v1/runs/{run_id}/approval` (wired, auto — Q8)
- Health: `GET {base}/health` (shallow, no LLM spend)

## Session & Run (hermes-owned)
- **Session**: persistent per-agent conversation; `session_id` stored on `AgentRecord`.
  Created lazily (`POST /api/sessions`), auto-recreated transparently if missing (U3 Q1=A).
- **Run**: a single turn's execution; `run_id` surfaced on every session-stream event →
  used only to **stop** the active turn. Not persisted.

## ChatEvent mapping (hermes SSE → existing U5 ChatEvent)
No new `ChatEvent` fields needed — the U5 model is a superset.

| hermes SSE event | → ChatEvent |
|---|---|
| `run.started` {run_id} | (internal) capture `run_id` for stop; no emit |
| `message.started` | (internal) begin assistant message; no emit |
| `assistant.delta` {delta} | `token` (data=delta) |
| `tool.progress` {tool_name=`_thinking`, delta} | `thinking` (data=delta) |
| `tool.progress` {tool_name≠_thinking, delta} | `tool_call` update (meta.status=in_progress) |
| `tool.started` {tool_name, args} | `tool_call` (meta: id, name, status=started, input=args) |
| `tool.completed` {tool_name, preview} | `tool_call` (meta: status=completed, output=preview) |
| `tool.failed` {tool_name, preview} | `tool_call` (meta: status=failed, output=preview) |
| `assistant.completed` {message} | (optional) fold into token stream; no duplicate emit |
| `run.completed` / `done` | terminal `done` |
| `error` {message} | terminal `error` (code=`agent_error`) |

`normalize_stream` guarantees exactly one terminal regardless of `run.completed`/`done`
ordering (terminal invariant preserved).

## HistoryTurn (reused; source changes)
Now sourced from `GET /api/sessions/{sid}/messages` (was ACP `session/load`). Same
`{role, text}` shape; best-effort, text-first.

## SandboxSnapshot → removed
The U7 `SandboxSnapshot` (single `sbx ls`, cached shallow health) is **removed** (NFR-U8-P1).
Status is queried live per request (Docker `ps`/`inspect` + parallel HTTP `/health`).
