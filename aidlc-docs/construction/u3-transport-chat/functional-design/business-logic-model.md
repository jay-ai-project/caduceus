# U3 Transport & Chat — Business Logic Model

Technology-agnostic flows for the `Transport` abstraction, `ChatService` (session continuity),
and `Supervisor` (RES-4/RES-5). Wire-protocol specifics of `hermes serve` are deferred to Build & Test;
this document defines the behavior the adapter must satisfy.

Decisions in force (Functional Design answers): **Q1=A** transparent session recreate · **Q2=B** no
caduceus-side per-agent serialization (concurrency delegated to `hermes serve`) · **Q3=A** standard
Supervisor defaults · **Q4=A** fail-fast on unhealthy/circuit-open · **Q5=A** protocol-handshake-only
health · **Q6=A** cooperative cancel.

---

## L1. Transport abstraction (FR-C3, FR-C4)

`Transport` is the single streaming interface caduceus uses to talk to an agent, so chat behavior is
identical across implementations (FR-C3) and a local `acp` optimization can be added later without
changing chat UX (FR-C4).

Interface (from component-methods C13):
```
async open() -> None
async close() -> None
async chat_stream(session_id: str|None, message: str) -> AsyncIterator[ChatEvent]
async health() -> HealthStatus
async get_config() -> ConfigSnapshot        # optional → NotSupported
async set_config(change) -> ConfigResult     # optional → NotSupported
@staticmethod for_agent(rec: AgentRecord) -> Transport
```

### ServeTransport.chat_stream (v1 flow)
1. Ensure open (lazy connect to the agent's `hermes serve` at the published host port; auth via `serve_auth`). On connect failure → yield one `error{code=transport_broken}` and stop (no tokens).
2. Send the turn (`session_id` may be `None` = start a new session) and **stream** backend output, mapping each backend chunk → `ChatEvent{token}`.
3. On normal end → yield exactly one `done{reason=completed}`. If the backend returns a whole message rather than chunks → yield `message` then `done`.
4. On mid-stream backend failure → yield one `error` with an appropriate `code` (`upstream_error`, `timeout`, `transport_broken`) and stop. No further events after a terminal event.
5. **Cooperative cancel (Q6=A)**: if the consumer stops iterating / signals cancel, send a best-effort cancel to the backend, close the stream, and emit `done{reason=cancelled, code=cancelled}`. The session is preserved (next turn may continue). No lock to release (Q2=B).

### ServeTransport.health (Q5=A — no LLM spend)
- Protocol-level handshake / lightweight non-inference call (e.g. version or session-list probe) against the serve port.
- Reachable+responsive → `HealthStatus(healthy, shallow=True)`. Unreachable/handshake fail → `unhealthy`.
- **Never** issues an LLM completion (honors the U2 deep-health contract). This is the `transport_healthy(rec)` probe U2's `HealthChecker` invokes for the deep check; end-to-end inference readiness is judged separately via U1 upstream reachability.

### Uniformity contract (FR-C3)
Given the same scripted sequence of backend outputs, **any** `Transport` implementation MUST yield the
same `ChatEvent` sequence (same types, same order, same terminal). This is the property that lets `acp`
drop in later — verified by a transport-parametrized PBT.

---

## L2. ChatService — chat orchestration + session continuity (FR-C1, FR-C2)

`chat_stream(name, message) -> AsyncIterator[ChatEvent]`:
1. **Resolve** `rec = Registry.get(name)`; unknown → one `error{code=agent_not_found}`.
2. **Gate (Q4=A fail-fast)**: if `rec.lifecycle == failed` or shallow-health is unhealthy → one `error{code=agent_unavailable}` with recovery guidance (`agent ls` / `agent start`); zero token events. Exception: a transient state (`creating`) gets a single short retry before deciding.
3. **Ensure session** via `_ensure_session(rec)` (L3).
4. **Stream**: obtain `Transport.for_agent(rec)`, delegate to `transport.chat_stream(session_id, message)`, and relay `ChatEvent`s to the caller unchanged.
5. **First-turn session persistence**: if the session was newly created (no prior `session_id`, or recreate), capture the backend's session id from the stream and persist it via `Registry.set_session(name, session_id)`.
6. **Concurrency (Q2=B)**: caduceus does **not** serialize turns per agent; concurrent turns are passed through and `hermes serve` arbitrates. (Documented user-accepted risk of session interleaving.)

`_ensure_session(rec) -> str|None` (Q1=A transparent recreate):
- If `rec.session_id` is set → attempt **resume**. If the backend reports the session is gone/expired → transparently **create a new session**, persist the new id, log one line (context may be lost); the user’s turn proceeds uninterrupted.
- If `rec.session_id` is unset → start with `session_id=None` (transport creates one) and persist the returned id.

---

## L3. Supervisor — health sweep + process supervision (RES-5, RES-4)

`start()` launches a periodic background sweep; `stop()` cancels it gracefully (no daemon crash, RES-4).

`_sweep()` — every **30s** (Q3=A default, Settings-tunable), for each managed agent:
1. Run deep health (via U2 `HealthChecker`, which calls U3’s `transport_healthy`). Healthy → reset that agent’s `AgentSupervisionState` (failures/restarts/backoff = 0, circuit `closed`).
2. **Local agent unhealthy**: increment `consecutive_health_failures`. On **≥2** consecutive failures and `circuit == closed` and `now ≥ next_attempt_at`:
   - Restart the agent’s `hermes serve` via U2 `Provisioner` (`stop`?→`start`/`start_serve`).
   - Increment `restart_attempts`, advance `backoff_index`, set `next_attempt_at = now + schedule[backoff_index]` (5s, 15s, 45s, … cap ~120s).
   - After **3** consecutive restart attempts that don’t restore health → **open the circuit**, mark the agent `failed` (via `AgentService`/`Registry`), stop auto-restarting. A manual `agent start` (U2) resets supervision state → `closed`.
3. **Remote agent unhealthy (BR-A10)**: cannot restart — mark `unhealthy`, attempt transport **reconnect** only on the next sweep.
4. The sweep never raises out of the loop; a probe/restart exception is logged and treated as a failed check.

Graceful degradation (RES-4): an unavailable agent or upstream degrades to a clear health state and a
fail-fast chat error; the daemon and other agents are unaffected.

---

## Testable Properties (PBT-01)

| ID | Property | Target |
|---|---|---|
| **PBT-U3-1** | Every `chat_stream` yields **exactly one** terminal event (`done` XOR `error`); no events follow a terminal; `token`/`message` only appear before it. | ChatService / Transport (scripted backend) |
| **PBT-U3-2** | `ChatEvent` `from_dict(to_dict(e)) == e` round-trip for all event types/codes. | ChatEvent |
| **PBT-U3-3** | **Transport uniformity** — for the same scripted backend output sequence, two `Transport` impls (Serve + a fake Acp) yield identical `ChatEvent` sequences. | Transport interface (FR-C3/C4) |
| **PBT-U3-4** | After a turn that creates/recreates a session, `Registry.get(name).session_id` is non-null and equals the id used; resume re-uses it; recreate replaces it (id changes only via create). | ChatService `_ensure_session` (FR-C2) |
| **PBT-U3-5** | **Fail-fast** — chat against a `failed`/unhealthy agent yields exactly one `error{code=agent_unavailable}` and **zero** token events. | ChatService gate (Q4) |
| **PBT-U3-6** | **Supervisor state machine** (stateful PBT) — across arbitrary health/restart-outcome sequences: `circuit==open ⇒ 0 restart attempts`; a healthy check resets all counters; `backoff_index` is monotone within an episode and clamped; remote agents never enter restart/circuit. | Supervisor / AgentSupervisionState (RES-5) |
| **PBT-U3-7** | **Cooperative cancel** — a cancelled turn terminates with `done{reason=cancelled}` (or `error{code=cancelled}`), preserves `session_id`, and emits no events afterward. | Transport/ChatService (Q6) |

Hypothesis seed logging (PBT-08) and stateful strategies follow the U2 pattern (reference model vs real
`Supervisor` driven over a `FakeProvisioner`/`FakeHealthChecker`).
