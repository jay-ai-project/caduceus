# U3 Transport & Chat — Logical Components

Logical (technology-agnostic) component view that realizes the NFR patterns. All collaborators from U2
are **injected as interfaces** (testability M-1); no real `hermes serve`/Docker in unit tests.

## Components (in `caduceus/transport/`)

### Transport (abstract) + ServeTransport
- **Role**: the streaming port to one agent. Methods: `open/close`, `chat_stream(session_id, message) -> AsyncIterator[ChatEvent]`, `health() -> HealthStatus`, optional `get_config/set_config` (→ `NotSupported`).
- **Patterns**: Adapter; timeout-per-call; lazy open; reconnect-on-broken; terminal-event guard; cooperative cancel.
- **ServeTransport** (v1): wraps a `websockets` client to the agent's published serve port; auth via `serve_auth`. All `hermes serve` wire specifics live here only.
- **State**: `TransportState` (closed/open/broken) in memory.

### Transport factory
- `Transport.for_agent(rec: AgentRecord) -> Transport` → `ServeTransport` for v1 (`serve`); `acp` reserved (FR-C4). Keeps construction out of `ChatService`/`Supervisor`.

### ChatService
- **Role**: chat orchestration + session continuity. `chat_stream(name, message)`: resolve `AgentRecord` (Registry) → **fail-fast gate** → `_ensure_session` (transparent resume/recreate, Q1) → delegate to `Transport.chat_stream` → relay events → persist new `session_id` via `Registry.set_session`.
- **Patterns**: fail-fast gate; terminal-event invariant; transparent session recreate; pass-through streaming.
- **Depends on (injected)**: `Registry` (U2), `Transport.for_agent`.

### Supervisor
- **Role**: periodic background task (RES-5). `start/stop` manage an `asyncio` task; `_sweep()` every 30s runs deep health per managed agent and drives restart/back-off/circuit for **local** agents; **remote** = probe + reconnect only.
- **Owns**: `{agent_name: AgentSupervisionState}` (failure count / restart attempts / backoff_index / next_attempt_at / circuit) — in memory.
- **Patterns**: health-sweep supervisor; circuit breaker; exponential back-off; supervised restart; fault isolation.
- **Depends on (injected)**: `HealthChecker` (U2, with U3's `transport_healthy` probe wired by U4), `Provisioner` (U2, restart local serve), `Registry`/`AgentService` boundary (mark `failed`).

## Component interaction (text)
```
U4 daemon (composition root)
  ├─ mounts ChatService.chat_stream → Control API POST /agents/{name}/chat (SSE)
  └─ starts Supervisor on gateway start; stops on gateway stop

ChatService ──uses──> Registry.get / set_session        (U2)
            ──uses──> Transport.for_agent ──> ServeTransport ──ws──> hermes serve (agent)

Supervisor  ──uses──> HealthChecker.check(deep)          (U2; calls U3 transport_healthy)
            ──uses──> Provisioner.stop/start/start_serve (U2, local restart)
            ──uses──> Registry / AgentService            (mark failed / read records)
```

## Injected interfaces (no concrete infra in unit tests)
| Dependency | Source | Test double |
|---|---|---|
| `Registry` (get/set_session/list) | U2 | in-memory fake |
| `HealthChecker.check` | U2 | fake returning scripted `HealthStatus` |
| `Provisioner` (stop/start/start_serve/status) | U2 | `FakeProvisioner` |
| backend protocol | `hermes serve` | **FakeTransport** (scripted `ChatEvent` sequences) |

## Realized properties (link to PBT-01)
- Adapter + terminal guard → **PBT-U3-1/3** (uniformity, single terminal).
- Session recreate → **PBT-U3-4**. Fail-fast gate → **PBT-U3-5**. Cooperative cancel → **PBT-U3-7**.
- Supervisor state machine (circuit/backoff/reset, remote-never-restart) → **PBT-U3-6** (stateful, vs reference model).

## Deferred to Infrastructure Design / Build & Test
- Exact `hermes serve` JSON-RPC methods, session/cancel verbs, auth header, and reconnect/keepalive tuning (same deferral convention as U2's sbx command lines). Confirm `websockets` vs `httpx`+SSE once the wire format is validated.
