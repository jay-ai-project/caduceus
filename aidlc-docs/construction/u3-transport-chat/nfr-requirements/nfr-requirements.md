# U3 Transport & Chat — NFR Requirements

Cross-cutting NFRs (requirements.md) + global stack are inherited from U1. This records **U3-specific**
targets/tunable defaults. **No new clarifying questions** — the global stack is locked and U3 NFRs derive
directly from the Functional Design answers (Q1–Q6) and the inherited resiliency scope.

## Performance (NFR-3 streaming)
- **P-1 Time-to-first-token**: chat is **pass-through** (BR-C6) — caduceus adds no buffering; per-token relay overhead must be negligible vs the LLM. Streaming, not request/response.
- **P-2 Health probe cost**: `transport_healthy` is a protocol handshake only (Q5/BR-C11) — sub-second, **zero LLM tokens**. Bounded by a per-probe timeout (default 5 s, shared with U2 `--deep`).
- **P-3 Supervisor overhead**: a 30 s sweep over a handful of agents is negligible; probes run concurrently and are individually timeout-bounded.

## Concurrency / Scalability
- **S-1 No caduceus-side turn serialization (Q2=B)**: concurrent chat turns to the same agent are passed through; `hermes serve` arbitrates. caduceus holds no per-agent turn-lock.
- **S-2 Async streaming**: transports are async iterators; many agents can be swept/chatted concurrently within the single daemon. Modest scale (a handful of agents).
- **S-3 Connection model**: one logical transport per agent; reconnect on `broken`. Connection pooling/reuse is a NFR-Design detail, not a requirement.

## Reliability (RES-4 / RES-5)
- **R-1 Timeouts on every transport call**: connect 10 s / idle 120 s / unary 300 s (shared-infrastructure defaults, Settings-tunable). Timeout → `error{code=timeout}`, never a hang (BR-C13).
- **R-2 Fail-fast (Q4)**: chat to a `failed`/circuit-open or shallow-unhealthy agent returns immediately with `error{code=agent_unavailable}` + recovery guidance; transient `creating` gets one short retry (BR-C14).
- **R-3 Graceful degradation**: an unavailable agent/upstream never crashes the daemon or affects other agents (BR-C15). Supervisor sweep loop is fault-isolated (BR-S7).
- **R-4 Supervision policy (Q3, local agents only)**: sweep 30 s; restart after ≥2 consecutive deep-health failures; exponential back-off 5/15/45 s cap ~120 s; circuit-open after 3 failed restart attempts → mark `failed`; reset on healthy check or manual `agent start` (BR-S1..S6). Remote = probe/reconnect only (BR-A10).
- **R-5 Stream termination invariant**: every turn ends with exactly one terminal event (`done` XOR `error`); cancellation is cooperative and preserves the session (BR-C5, BR-C10).

## Security (baseline; Security ext OFF)
- **SEC-1 serve_auth handling**: the agent `hermes serve` credential (`AgentRecord.serve_auth`) is sent only over the transport auth channel, never logged (redaction), consistent with U2 SEC-1/SEC-2.
- **SEC-2 Loopback reach**: published serve ports are reached over the host loopback/bridge; no LAN exposure introduced by U3.

## Observability (RES-6 / RESILIENCY-05)
- Structured, secret-redacting logs for: session resume/recreate (Q1), restart attempts, back-off, circuit transitions, and terminal chat errors (BR-C16). Metrics/traces/dashboards **N/A** (personal tool).

## Maintainability / Testability (NFR-5, PBT)
- **M-1 Interfaces mocked**: `Transport` is abstract; unit tests drive a **FakeTransport**/scripted backend and a `FakeProvisioner`/`FakeHealthChecker` for the Supervisor — no real `hermes serve`/Docker in unit tests.
- **M-2 PBT (PBT-01/09)**: the 7 U3 properties, incl. **PBT-U3-3 transport uniformity** (Serve vs fake Acp yield identical event streams) and **PBT-U3-6 stateful Supervisor** (`RuleBasedStateMachine` vs reference model). Hypothesis with seed logging (PBT-08).
- **M-3 Real protocol** (`hermes serve` wire format, reconnect, cancel verb) exercised only in **Build & Test** integration + RESILIENCY-14 fault injection (kill/restart serve, drop connection).

## Resiliency scope realized in U3
- **RESILIENCY-10 (dependency isolation)** → R-1, R-2, R-3 (timeouts, fail-fast, graceful degradation).
- **RESILIENCY-05 (observability)** → logging only (above).
- **Process supervision (RES-5)** → R-4 (Supervisor). **RESILIENCY-14** fault-injection tests deferred to Build & Test (already project-wide decision).

## Out of scope (v1)
- Transport connection pooling/multiplexing tuning; ACP transport implementation (FR-C4 designed-for only).
- Remote agent process lifecycle/restart (BR-A10). Multi-session per agent (one persistent session, BR-C1).
- Rate limiting / per-agent concurrency caps (Q2=B delegates concurrency to hermes).
