# U3 Transport & Chat — Business Logic Summary (code)

Generated files under `caduceus/transport/` (application code; workspace root).

## Modules
| File | Responsibility | Key rules |
|---|---|---|
| `transport/events.py` | `ChatEvent`/`ChatEventType` (+ `to_dict`/`from_dict`, convenience ctors) and `normalize_stream()` — the shared terminal-guard relay (exactly one `done` XOR `error`; nothing after; missing→append done; exception→error). | BR-C5/C6; PBT-U3-1/2 |
| `transport/base.py` | `Transport` ABC: `open/close/health` + abstract `_raw_stream`; concrete `chat_stream = normalize_stream(_raw_stream)` so all transports behave identically; `request_cancel` (cooperative); `for_agent` factory (v1→ServeTransport); `get/set_config`→`NotSupported`; `TransportState`/`TransportKind`. | FR-C3/C4; BR-C7/C8/C10 |
| `transport/serve.py` | `ServeTransport` (v1) over `hermes serve` — lazy `websockets` import, lazy open + reconnect-on-broken, per-call timeouts (`asyncio.wait_for`), cooperative cancel, handshake-only `health()` (no LLM). Wire codec isolated in `_WIRE_*` methods **flagged for Build & Test**. | BR-C10..C13; Q5; SEC-1 |
| `transport/chat.py` | `ChatService.chat_stream` — resolve `AgentRecord` → **fail-fast gate** (failed/unhealthy→`agent_unavailable`; `creating`→one retry) → open transport → relay events → persist (possibly recreated) `session_id` in `finally`. No turn-lock (Q2). | FR-C1/C2; BR-C1..C4/C14; Q1/Q4 |
| `transport/supervisor.py` | `Supervisor` background sweep (`start/stop`, `_sweep`) + `AgentSupervisionState`/`CircuitState`/`DEFAULT_BACKOFF`. Local: ≥2 fails→restart, exp back-off, 3 restart-fails→circuit open + `mark_failed`; healthy→reset; `reset_agent` for manual recovery. Remote: probe-only, never restart. Fault-isolated loop. Injected callables (`list_agents`/`health_check`/`restart`/`mark_failed`). | RES-5; BR-S1..S7; Q3 |

## Decoupling / wiring
- All U2 collaborators are **injected** (Registry sync `get`/`list` + async `set_session`; `health_check`/`restart`/`mark_failed` callables) so U3 is unit-testable with fakes and U4 wires the real Provisioner/Registry/HealthChecker at composition time.
- Session continuity: transport sets `self.session_id` (resume or transparent recreate); `ChatService` persists it via `Registry.set_session` only when it changed.

## Dependency
- Added `websockets>=12` to `pyproject.toml` (lazy-imported in `serve.py`; unit suite runs without it).
