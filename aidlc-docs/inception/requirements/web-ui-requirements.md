# Requirements — Gateway Web UI (Unit U5)

## Intent Analysis
- **User request**: `caduceus gateway` 실행 시 간단한 Web UI 제공 — agent 대시보드(프로비저닝/연결 상태), 신규 agent 추가(로컬 sandbox 생성 + remote 등록, 실시간 상태), 각 agent 와 streaming chat(thinking + tool 호출 여부/결과 표시). 세션 영속화 불필요(휘발 OK)이나 sandbox 내 hermes 세션 기록 불러오기는 가능하면 구현.
- **Request type**: New Feature (new development cycle on a completed project → candidate Unit **U5**).
- **Scope**: Multiple Components — new `webui` surface mounted on the daemon Control API, **plus** an extension of the existing chat event model + ACP transport (cross-cutting into U3 transport).
- **Complexity**: Moderate. Frontend is simple (static SPA reusing existing endpoints); the non-trivial backend work is surfacing **thinking / tool-call** events that are currently discarded.

## Confirmed Decisions (from web-ui-verification-questions.md)
| # | Decision |
|---|---|
| Q1 | **A** — Self-contained static vanilla SPA (HTML/JS/CSS), **no build step**, served by the daemon. |
| Q2 | **A** — Mount Web UI on the existing **Control API loopback listener** (`127.0.0.1:9700`); reuse existing endpoints. |
| Q3 | **A** — **Full** thinking + tool display: stream thinking text, tool name + args + results in collapsible inline sections. |
| Q4 | **A** — Agent add at **parity with CLI**: local sandbox provision (live SSE progress) **and** remote register. |
| Q5 | **A** — Load chat history by resuming the persisted session and capturing **ACP `session/load` replay** (best-effort). |
| Q6 | **A** — **Loopback-only, no auth** (personal local tool; same exposure as Control API). |
| Q7 | **A** — Dashboard liveness via **periodic polling**. |
| Q8 | **A** — Inherit project extensions: Security=No, Resiliency=Yes (full), Property-Based Testing=Yes (full). |
| Q9 | (blank) — no extra constraints; scope limited to dashboard + add + chat as described. |

## Functional Requirements

### FR-W1 — Static Web UI serving
- The daemon serves a self-contained static SPA at the Control API listener root (`http://127.0.0.1:9700/`). No build toolchain; assets shipped in the package and mounted via FastAPI.

### FR-W2 — Dashboard
- List all agents with: name, kind (local/remote), lifecycle (creating/running/stopped/failed), health, endpoint/connection info, model alias, has-session, created-at.
- Show gateway status (running, listeners, upstream, agent count, version).
- Auto-refresh via periodic polling (Q7). Reuses `GET /status`, `GET /agents`.

### FR-W3 — Add agent (local provision)
- Create a local sandboxed agent from the UI (name + optional model/upstream/image), showing **live provisioning progress** (preparing/building/loading image → creating sandbox → configuring → verifying), then final result/error. Reuses `POST /agents` (SSE).

### FR-W4 — Add agent (remote register)
- Register a remote hermes endpoint (name + endpoint URL + optional auth) from the UI, displaying returned guidance. Reuses `POST /agents/register`.

### FR-W5 — Agent lifecycle actions
- From the dashboard: stop / start / remove an agent. Reuses `POST /agents/{name}/stop|start`, `DELETE /agents/{name}`. (Remote start/stop remains unsupported per BR-A10 — UI must reflect/disable accordingly.)

### FR-W6 — Streaming chat
- Enter a chat view per agent; send a message; stream the assistant response token-by-token. Reuses `POST /agents/{name}/chat` (SSE) consumed via browser `fetch` + streaming reader.

### FR-W7 — Thinking display
- During a turn, render the agent's **thinking** (reasoning) stream distinctly from the final answer (e.g., a collapsible "thinking" block). **Requires** new event surfacing (see FR-W9).

### FR-W8 — Tool-call display
- During a turn, render **tool calls**: tool name, status (started/completed/failed), input args, and result/output, as collapsible inline sections. **Requires** new event surfacing (see FR-W9).

### FR-W9 — Chat event-model extension (enabler, cross-cutting U3)
- Extend `ChatEvent` (`transport/events.py`) with non-terminal event types for **thinking** and **tool call** (start/update/result), preserving the existing terminal invariant (exactly one `done`/`error`; nothing after terminal).
- Extend `AcpTransport._prompt` (`transport/acp.py`) to translate hermes ACP `session/update` variants — `agent_thought_chunk` (thinking) and `tool_call` / `tool_call_update` (tool calls) — into the new events instead of dropping them.
- The Control API chat SSE relays the new event types unchanged (already serializes `ChatEvent.to_dict()`).
- **Backward compatibility**: CLI chat renderer must continue to function; new event types are additive (CLI may ignore or lightly render them).

### FR-W10 — Session history load (best-effort)
- On entering an agent's chat view, attempt to load and render prior turns by resuming the agent's persisted session and capturing the ACP `session/load` replay (`session/update` notifications). If unsupported or unavailable, start empty without error. Local sbx agents only (remote deferred).

## Non-Functional Requirements
- **NFR-W1 (Usability)**: Minimal, readable single-page layout (dashboard ↔ chat). No external CDN/runtime dependency required at load (offline-capable for a local tool); vanilla JS.
- **NFR-W2 (Security/Exposure)**: Loopback-only, no auth (Q6). Web UI must NOT be served on the public AI-Gateway listener (`0.0.0.0:9701`). No secrets (tokens/serve_auth) projected to the browser — reuse the secret-free `AgentView`.
- **NFR-W3 (Resiliency — inherited, full)**: Graceful handling of daemon-not-running / agent unavailable / SSE disconnect in the UI; chat errors surfaced in-band (terminal `error` event) rather than hanging. Health/lifecycle reflected accurately.
- **NFR-W4 (Testability / PBT — inherited, full)**: The event-model extension (FR-W9) is pure/translatable and unit-testable with a fake ACP agent (no Docker); the terminal-event invariant under the extended event set is a property worth PBT coverage. Static frontend asset serving is integration-validated.
- **NFR-W5 (Packaging)**: Static assets packaged into the wheel (hatch build target) so `caduceus` installed from a wheel still serves the UI.

## Out of Scope (v1)
- Persisting chat transcripts to caduceus-side storage (explicitly not required).
- Remote-agent session history loading (deferred).
- Agent config editing UI and logs viewer (not requested in Q9; backend endpoints exist for future addition).
- Authentication / multi-user / remote exposure.

## Key Requirements Summary
- A no-build static SPA on the loopback Control API gives **dashboard + add(local/remote) + streaming chat** mostly by reusing existing endpoints.
- The **核심 enabler** is FR-W9: extend the chat event model + ACP transport to surface **thinking and tool calls** that are presently discarded — without breaking the terminal-event invariant or the CLI.
- History loading (FR-W10) rides on ACP `session/load` replay, best-effort.
- Inherits Resiliency (full) and PBT (full); Security Baseline stays disabled.
