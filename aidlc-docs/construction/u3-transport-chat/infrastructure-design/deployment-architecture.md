# U3 Transport & Chat — Deployment / Runtime Architecture

U3 deploys **nothing of its own** — it runs as modules inside the caduceus daemon. This shows the
runtime paths for **chat** and **supervision**, plus failure modes.

## Runtime view
```
                         caduceus daemon (one process, host)
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Control API (127.0.0.1:9700)                                          │
  │     POST /agents/{name}/chat ──► ChatService.chat_stream (SSE out)     │
  │                                     │                                  │
  │   ChatService ── Registry.get/set_session (U2 state.json)             │
  │        │                                                              │
  │        └─ Transport.for_agent(rec) ─► ServeTransport ──┐              │
  │                                                         │              │
  │  Supervisor (asyncio task, 30s sweep)                   │              │
  │     ├─ HealthChecker.check(deep) ─► transport_healthy ──┤ (probe)      │
  │     └─ Provisioner.start_serve (local restart) ─────────┼──► sbx       │
  └─────────────────────────────────────────────────────────┼─────────────┘
                                                             │ ws
                          local: 127.0.0.1:<serve_port> ◄────┘────► hermes serve (sbx, :9119)
                          remote: AgentRecord.endpoint  ◄─────────► hermes serve (remote host)
```

Text alternative: A user `chat` hits the daemon's loopback Control API, which calls `ChatService`.
`ChatService` resolves the `AgentRecord` from the U2 registry, gets a `Transport` via the factory, and
streams `ChatEvent`s back as SSE. In parallel, the `Supervisor` background task sweeps every 30s, running
deep health (using U3's no-LLM `transport_healthy` probe) and, for local agents, restarting a dead
`hermes serve` via the U2 `Provisioner`. Transports connect over WebSocket to the published host port
(local) or the registered endpoint (remote).

## Lifecycle binding
- `gateway start` → daemon builds apps (U4), then `Supervisor.start()`.
- `gateway stop` → `Supervisor.stop()` (cancel sweep, close transports), drain, release lock.

## Failure modes & responses
| Failure | Detection | Response |
|---|---|---|
| Agent `hermes serve` dies (local) | sweep deep-health fail ×2 | restart via Provisioner, exp back-off; circuit-open→`failed` after 3 fails |
| Agent unreachable (remote) | health fail | mark `unhealthy`; reconnect next sweep; **no restart** (BR-A10) |
| Connection drops mid-stream | transport error | terminal `error`; transport→`broken`; reopened on next use |
| Backend stalls | idle timeout | `error{code=timeout}`; no hang |
| Stored session gone | resume rejected | transparent recreate (Q1), persist new `session_id` |
| User cancels turn | consumer cancel | cooperative cancel → `done{reason=cancelled}`; session kept |
| Upstream (LLM) down | deep-health `degraded` (U1 probe) | chat surfaces upstream error; daemon + agents stay up |

## Environments
- Single environment: the user's local host (WSL2 + Docker), same as U1/U2. No cloud, no staging/prod split.
