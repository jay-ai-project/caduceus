# U3 Transport & Chat — Business Rules

Authoritative rule list for U3. IDs `BR-C*` (chat/session/transport) and `BR-S*` (supervision).
Each rule is technology-agnostic and traces to a requirement.

## Session & continuity (FR-C1, FR-C2)
- **BR-C1** — Each agent has **at most one** persistent session, stored as `AgentRecord.session_id`. caduceus does not create a second session for the same agent while one exists.
- **BR-C2** — `chat` **auto-resumes** the stored session when present (no user action needed).
- **BR-C3 (Q1=A)** — If resuming a stored `session_id` fails because the session no longer exists (agent restarted / expired / re-provisioned), caduceus **transparently creates a new session**, persists the new id, and logs one line. The turn proceeds; the user is not blocked. Prior conversation context may be lost (best-effort continuity).
- **BR-C4** — A newly created session’s id MUST be persisted via `Registry.set_session(name, id)` **before or as** the first turn completes, so the next `chat` resumes it. `session_id` changes only via create/recreate — never silently mutated.

## Chat streaming & events (FR-C1, FR-C3)
- **BR-C5** — Every `chat_stream` terminates with **exactly one** terminal event: `done` (normal/cancel) **or** `error`. No `token`/`message` may follow a terminal event.
- **BR-C6** — Streaming is **pass-through**: backend chunks map 1:1 to `token` events in order; caduceus does not buffer the whole response before emitting.
- **BR-C7 (FR-C3 uniformity)** — Chat behavior — event types, ordering, terminal semantics, error mapping — MUST be identical across all `Transport` implementations. Any behavior that cannot be made uniform belongs below the interface, not in `ChatService`.
- **BR-C8 (FR-C4)** — The `Transport` interface MUST remain implementation-neutral (no `serve`-only concepts leak into `ChatService`/CLI), so an `acp` transport can be added behind `Transport.for_agent` without changing chat UX.

## Concurrency (Q2=B)
- **BR-C9** — caduceus does **not** serialize concurrent chat turns to the same agent; concurrency is delegated to `hermes serve`. (User-accepted trade-off: simpler caduceus, possible session interleaving if the user runs two turns at once.)

## Cancellation (Q6=A)
- **BR-C10** — On consumer cancel (e.g. Ctrl-C), caduceus performs a **cooperative cancel**: best-effort cancel signal to the transport, close the stream, emit `done{reason=cancelled}` (or `error{code=cancelled}`). The session is **preserved** for the next turn. No lock is held to release (per BR-C9).

## Transport health (FR-L2 deep probe, Q5=A)
- **BR-C11** — `Transport.health()` performs **only** a protocol-level handshake / non-inference probe. It MUST NOT issue an LLM completion (honors U2’s "deep check spends no LLM" contract).
- **BR-C12** — Transport health answers "is the agent endpoint alive/responsive"; **inference readiness** (upstream reachable) is a separate signal owned by U1 and combined by the U2 `HealthChecker`.

## Timeouts & isolation (RES-4)
- **BR-C13** — All transport calls use explicit timeouts (connect / idle / unary) from Settings (shared-infrastructure defaults: connect 10s, idle 120s, unary 300s). A timeout yields `error{code=timeout}`, never a hang.
- **BR-C14 (fail-fast, Q4=A)** — A `chat` to an agent that is `failed`/circuit-open or shallow-unhealthy returns **immediately** with `error{code=agent_unavailable}` and recovery guidance — no token events, no long timeout wait. A transient `creating` state gets a single short retry before the gate decides.
- **BR-C15** — A failing agent or upstream MUST degrade gracefully: mark health, surface a clear error, and **never crash the daemon** or affect other agents.

## Supervision (RES-5) — local agents only (BR-A10 inherited)
- **BR-S1** — The Supervisor manages **local** agents only. Remote agents are **probe-only**: it may mark them unhealthy and reconnect the transport, but MUST NOT attempt start/stop/restart (BR-A10).
- **BR-S2 (Q3=A)** — Sweep interval default **30s** (Settings-tunable). Each sweep runs a deep health check per managed agent.
- **BR-S3** — A local agent is restarted (via U2 `Provisioner`) after **≥2 consecutive** deep-health failures, gated by back-off.
- **BR-S4** — Restart back-off is **exponential** (schedule 5s → 15s → 45s → … capped ~120s); `next_attempt_at` enforces the gate; no restart runs before it.
- **BR-S5 (circuit-break)** — After **3 consecutive** restart attempts fail to restore health, **open the circuit**: mark the agent `failed`, stop auto-restarting. The circuit (and all supervision counters) reset to `closed` only on a successful health check or a manual `agent start`.
- **BR-S6** — A healthy deep-check resets `consecutive_health_failures`, `restart_attempts`, `backoff_index` to 0 and `circuit` to `closed` for that agent.
- **BR-S7** — The sweep loop is fault-isolated: any probe/restart exception is logged and treated as a failed check; it never breaks the loop or the daemon (RES-4).

## Observability (RES-6 / RESILIENCY-05)
- **BR-C16** — Session recreate, restart attempts, circuit transitions, and terminal chat errors are logged via the shared secret-redacting structured logger (`serve_auth`/tokens never logged in clear). Metrics/traces/dashboards are N/A for this personal tool.

---

## Local vs remote capability matrix
| Capability | Local (sbx) | Remote (registered) |
|---|---|---|
| chat (stream, session resume) | ✅ | ✅ |
| transport health probe (no LLM) | ✅ | ✅ |
| auto-restart on failure | ✅ (Supervisor) | ❌ (BR-A10 / BR-S1) |
| circuit-break → `failed` | ✅ | ❌ (mark `unhealthy` only) |
| reconnect transport | ✅ | ✅ |

## Traceability
- FR-C1 → BR-C5..C6, C10, C14 · FR-C2 → BR-C1..C4 · FR-C3 → BR-C7, C11 · FR-C4 → BR-C8.
- RES-4 → BR-C13..C15, BR-S7 · RES-5 → BR-S1..S6 · RES-6 → BR-C16.
- Inherited: BR-A10 (remote no start/stop) → BR-S1; U2 deep-health no-LLM contract → BR-C11.
