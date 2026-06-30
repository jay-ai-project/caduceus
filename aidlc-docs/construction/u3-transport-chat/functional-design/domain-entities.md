# U3 Transport & Chat — Domain Entities

Technology-agnostic domain model for U3. Reuses `AgentRecord`, `HealthStatus`, `HealthLevel`,
`Lifecycle`, `AgentKind` from `caduceus/common/models.py` (owned by U2) — U3 adds chat/transport/supervision
concepts only. No infrastructure types here (wire protocol, sockets → Build & Test).

## Reused (from `common/`)
- **`AgentRecord`** — carries `kind`, `endpoint`, `serve_port`, `serve_auth`, `session_id`, `lifecycle`. U3 reads it via `Registry.get(name)` and persists session changes via `Registry.set_session(name, session_id)`.
- **`HealthStatus` / `HealthLevel`** — returned by `Transport.health()` and consumed by the U2 `HealthChecker` deep-probe.
- **`Lifecycle`** — U3 reads `running/stopped/failed/registered` and (via the Supervisor) requests a transition to `failed` when a local agent's circuit opens. Only U2 `AgentService`/`Registry` mutate persisted lifecycle; the Supervisor calls into that boundary rather than writing state directly.

---

## ChatEventType (enum)
| Value | Meaning |
|---|---|
| `token` | An incremental output chunk (streamed). Zero or more per turn. |
| `message` | A complete assistant message (terminal-adjacent; may be emitted once when a turn yields a whole message rather than tokens). |
| `error` | A terminal failure for this turn (carries a message + machine code). |
| `done` | Terminal success/normal-end marker (carries optional reason, e.g. `completed`, `cancelled`). |

**Terminal events**: `done` and `error`. Exactly one terminal event ends every turn (see PBT-01 in business-logic-model).

## ChatEvent
| Field | Type | Notes |
|---|---|---|
| `type` | `ChatEventType` | required |
| `data` | `str` | token text, full message text, or error/`done` reason; never `None` (empty string allowed) |
| `code` | `str?` | machine code for `error` (e.g. `agent_unavailable`, `upstream_error`, `transport_broken`, `timeout`, `cancelled`); `None` otherwise |

> Serialization is explicit (`to_dict`/`from_dict`) so the SSE layer (U4) and PBT round-trips are stable.

## ChatTurn (transient, not persisted)
One request→stream interaction. Conceptual fields:
| Field | Type | Notes |
|---|---|---|
| `agent_name` | `str` | target agent |
| `session_id` | `str?` | resolved session for this turn (after ensure-session) |
| `message` | `str` | user input |
| `cancelled` | `bool` | set when the consumer requests cooperative cancel (Q6=A) |

A `ChatTurn` is realized as an `AsyncIterator[ChatEvent]`; it owns no durable state beyond the `session_id` it may persist on first creation.

---

## TransportState (enum) — per live Transport instance
| Value | Meaning |
|---|---|
| `closed` | Not opened / cleanly closed. |
| `open` | Connected and usable. |
| `broken` | Connection failed mid-use; needs reopen. The Supervisor/ChatService may discard and recreate. |

`Transport` is created per agent via the factory `Transport.for_agent(rec)`; v1 returns a `ServeTransport`. State is in-memory only.

## TransportKind (enum) — for the factory (FR-C4 extensibility)
| Value | v1 |
|---|---|
| `serve` | **implemented** — talks to the agent's `hermes serve` (host port = `AgentRecord.serve_port`, auth = `serve_auth`). |
| `acp` | **designed-for, not built** — local stdio optimization; plugs in behind the same `Transport` interface without changing chat UX. |

Selection rule (v1): every `AgentRecord` → `serve`. (`acp` reserved for a future local-optimization flag.)

---

## Supervision domain (RES-5 / RES-4)

### CircuitState (enum)
| Value | Meaning |
|---|---|
| `closed` | Normal. Restarts allowed on failure. |
| `open` | Tripped after repeated restart failures. No further auto-restart; agent marked `failed`. Resets to `closed` on manual `agent start`. |

### AgentSupervisionState (in-memory, per managed local agent)
| Field | Type | Notes |
|---|---|---|
| `agent_name` | `str` | key |
| `consecutive_health_failures` | `int ≥ 0` | reset to 0 on any healthy deep-check |
| `restart_attempts` | `int ≥ 0` | consecutive restart attempts in the current failure episode |
| `backoff_index` | `int ≥ 0` | index into the back-off schedule (5s, 15s, 45s, … cap ~120s) |
| `next_attempt_at` | `timestamp?` | earliest time the next restart may run (back-off gate) |
| `circuit` | `CircuitState` | `closed` default |

**Scope**: only **local** agents get an `AgentSupervisionState`. Remote agents (BR-A10) are probe-only — they have health but no restart/circuit machinery.

**Invariants** (enforced as PBT-01 properties):
- `circuit == open` ⇒ no restart is attempted and `restart_attempts` is frozen.
- A healthy deep-check resets `consecutive_health_failures`, `restart_attempts`, `backoff_index` to 0 and `circuit` to `closed`.
- `backoff_index` only increases on a restart attempt and is clamped to the schedule length.

---

## Entity relationships (text)
- `ChatService` —uses→ `Registry` (resolve `AgentRecord`) and `Transport.for_agent(rec)` (one transport per turn or pooled per agent).
- `Transport` —produces→ `AsyncIterator[ChatEvent]`; —reports→ `HealthStatus`.
- `Supervisor` —owns→ `{agent_name: AgentSupervisionState}`; —uses→ U2 `HealthChecker`/`Provisioner` (restart local serve) and `Registry`/`AgentService` (mark `failed`).
- `AgentRecord.session_id` is the single durable link between turns (FR-C2 continuity); everything else in U3 is in-memory.
