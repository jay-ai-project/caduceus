# U3 Transport & Chat — API / Test Summary (code)

## Public surface (consumed by U4 daemon/CLI)
- `ChatService.chat_stream(name, message) -> AsyncIterator[ChatEvent]` — mounted by the Control API `POST /agents/{name}/chat` (SSE) in U4.
- `Supervisor(start/stop, reset_agent)` — started on `gateway start`, stopped on `gateway stop`.
- `Transport` / `Transport.for_agent(rec)` / `ServeTransport` — transport abstraction.
- `ChatEvent` / `ChatEventType` — uniform streaming event (SSE-serializable via `to_dict`).

U3 exposes **no HTTP listener of its own** (it is an outbound client + in-daemon task); the chat HTTP route lives in U4 per the component-methods contract (C4 `POST /agents/{name}/chat`).

## Tests (all green: `pytest` → 81 passed; U3 contributes 26)
| File | Covers |
|---|---|
| `tests/unit/test_chat_events.py` | round-trip; normalize terminal-guard (passthrough, truncate-after-terminal, append-done, exception→error) |
| `tests/unit/test_chat_service.py` | unknown agent; fail-fast (failed lifecycle + unhealthy, zero tokens); `creating` one-retry; happy relay + new-session persist; resume-no-repersist; transparent recreate persist; open-failure fail-fast; cooperative cancel + session preserved |
| `tests/unit/test_supervisor.py` | healthy=no-restart; restart after threshold; circuit-open + mark_failed + no-restart-after; back-off gate; recovery reset; remote-never-restart; health-probe exception isolation; `reset_agent` |
| `tests/pbt/test_transport_properties.py` | PBT-U3-2 ChatEvent round-trip; PBT-U3-1 single-terminal; PBT-U3-3 transport uniformity (Serve-like vs Acp-like); PBT-U3-6 stateful Supervisor invariants (local+remote) |

Test doubles added to `tests/fakes.py`: `make_agent`, `FakeRegistry`, `FakeTransport` (scripted events, recreate, cancel), `ServeLikeFake`/`AcpLikeFake` (uniformity).

## Not unit-tested by design (→ Build & Test)
- `ServeTransport._WIRE_*` (real `hermes serve` protocol) — same convention as U2's `SbxProvisioner`. Validated in Build & Test integration + RESILIENCY-14 fault injection (kill/restart serve, drop connection mid-stream, stall→timeout), per U3 Infra Design validation items.

## PBT-08
- Hypothesis seed/repro logging via the existing `tests/conftest.py` profile (shared with U1/U2).
