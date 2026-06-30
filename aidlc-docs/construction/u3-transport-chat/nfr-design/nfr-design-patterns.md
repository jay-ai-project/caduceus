# U3 Transport & Chat — NFR Design Patterns

Realizes U3's NFRs. Project-wide resiliency process decisions (CI / rollback / resiliency-testing /
incident) were settled at U1 NFR Design and are inherited. Patterns below derive from the locked FD
decisions (Q1–Q6).

## Resilience patterns (RES-4 RESILIENCY-10 / RES-5 supervision)
| Pattern | Application | Traces |
|---|---|---|
| **Adapter (port/abstraction)** | `Transport` (abstract) hides the agent protocol; `ServeTransport` (v1) and a future `AcpTransport` are interchangeable. `ChatService`/`Supervisor` depend only on the abstraction → uniform behavior (FR-C3) + pluggable optimization (FR-C4). | BR-C7/C8 |
| **Timeout on every transport call** | connect 10s / idle 120s / unary 300s (Settings-tunable) via `asyncio.wait_for`; a stall yields `error{code=timeout}`, never a hang. | BR-C13 / R-1 |
| **Circuit breaker (per local agent)** | `AgentSupervisionState.circuit`: after 3 consecutive failed restart attempts → **open** (mark `failed`, stop auto-restart). Resets to **closed** on a healthy deep-check or manual `agent start`. | BR-S5 / R-4 |
| **Exponential back-off** | restart schedule 5s → 15s → 45s → … cap ~120s, gated by `next_attempt_at`; no restart before the gate. | BR-S4 |
| **Fail-fast gate** | `ChatService` checks lifecycle/shallow-health before streaming; `failed`/circuit-open/unhealthy → immediate `error{code=agent_unavailable}` + recovery guidance (transient `creating` gets one short retry). | BR-C14 / R-2 |
| **Supervised restart (local only)** | periodic sweep restarts a dead local `hermes serve` via the injected U2 `Provisioner`; **remote agents are probe/reconnect-only** (BR-A10). | BR-S1..S3 |
| **Reconnect on broken transport** | a `broken` transport is discarded and reopened on next use/sweep; transient connection loss self-heals. | S-3 |
| **Cooperative cancellation** | consumer cancel → best-effort cancel to backend → `done{reason=cancelled}`; session preserved, no lock held (Q2=B). | BR-C10 |
| **Fault isolation / graceful degradation** | the sweep loop swallows+logs per-agent probe/restart exceptions; one agent's failure never crashes the daemon or blocks others. | BR-C15 / BR-S7 / R-3 |
| **Terminal-event invariant** | every stream ends with exactly one `done` XOR `error`; tokens only precede it (enforced by a small state guard in the relay). | BR-C5 / R-5 |

## Performance patterns (NFR-3)
- **Streaming pass-through**: backend chunks relayed 1:1 as `token` events via an async generator — no whole-response buffering (BR-C6).
- **Protocol-only health probe**: `transport_healthy` does a handshake/non-inference call, sub-second, **zero LLM tokens** (BR-C11); honors U2's deep-health contract.
- **Concurrency delegated**: no caduceus turn-lock (Q2=B); concurrent turns pass straight through to `hermes serve`. Sweep probes run concurrently, each timeout-bounded.
- **Lazy transport open**: connect on first use; reuse the open transport for subsequent turns/probes of the same agent.

## Security patterns (baseline; Security ext OFF)
- **Secret-in-transit only**: `serve_auth` sent solely over the transport auth channel; never placed in logs or argv. Routed through the shared redaction filter (consistent with U2 SEC-1/2).
- **No new exposure**: transports reach published serve ports over host loopback/bridge; U3 opens no LAN listener.

## Observability (RES-6 / RESILIENCY-05)
- Structured events (secrets redacted): `{event: session_resume|session_recreate|restart_attempt|circuit_open|chat_error, agent, backoff_index?, attempt?, code?, duration_ms}`. Metrics/traces/dashboards N/A (personal tool).

## Resolved project-wide decisions (inherited from U1 NFR Design)
- CI = GitHub Actions (pytest + Hypothesis, seed-logged); rollback = reinstall previous pinned version; deploy = direct install; resiliency testing = lightweight fault injection (here: kill/restart `hermes serve`, drop the connection mid-stream, stall the backend → assert timeout/restart/circuit behavior); incident = log-based triage + restart.
