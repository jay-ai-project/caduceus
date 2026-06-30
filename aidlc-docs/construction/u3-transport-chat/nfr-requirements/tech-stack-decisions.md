# U3 Transport & Chat — Tech Stack Decisions

Inherits the global stack (Python 3.11+, `asyncio`, FastAPI/`httpx` from U1, pytest + Hypothesis).
U3 adds **one** runtime dependency: a WebSocket client for the serve transport.

| Concern | Choice | Rationale |
|---|---|---|
| Serve transport client | **`websockets`** (async) for `hermes serve` JSON-RPC/WebSocket; `httpx` for any HTTP/SSE parts | matches the architecture (Transport v1 = `hermes serve` JSON-RPC/WS, requirements.md); async streaming; already earmarked in `pyproject.toml` ("websockets added in U3") |
| Async streaming | stdlib `asyncio` + `AsyncIterator[ChatEvent]` | uniform streaming surface across transports (FR-C3) |
| Timeouts/cancellation | `asyncio.wait_for` / task cancel + explicit connect/idle/unary timeouts | RES-4 isolation; cooperative cancel (Q6/BR-C10) |
| Supervisor scheduling | stdlib `asyncio` background task + monotonic clock for back-off | no new dep; cancellable on daemon stop |
| Event/state models | dataclasses in `caduceus/transport/` (`ChatEvent`, `AgentSupervisionState`) + reused `common` models | consistent with U1/U2; explicit `to_dict/from_dict` for PBT round-trip |
| Transport factory | `Transport.for_agent(rec)` returning `ServeTransport` (v1); `acp` reserved | FR-C4 extensibility without dep churn |

## Why not alternatives
- **Raw `httpx` WS / aiohttp**: `websockets` is the lightest, focused async WS lib; aiohttp would duplicate httpx's HTTP role. If Build & Test reveals `hermes serve` actually speaks HTTP+SSE (not WS), the transport falls back to the already-present `httpx` (no new dep) — decided at protocol validation.
- **No threads**: everything stays in the single asyncio loop of the daemon (consistent with U1/U2).

## Testing (PBT-09 satisfied globally)
- **Unit**: `pytest` with a **FakeTransport** (scripted `ChatEvent` sequences) and fake Provisioner/HealthChecker — no real `hermes serve`/Docker.
- **Property**: **Hypothesis** — `ChatEvent` round-trip (PBT-U3-2), transport uniformity (PBT-U3-3), stream-termination/fail-fast/cancel invariants (PBT-U3-1/5/7), and a `RuleBasedStateMachine` for the Supervisor (PBT-U3-6). Seed logging via existing `conftest.py` profiles (PBT-08).
- **Integration** (Build & Test): real `hermes serve` in an sbx agent — stream a turn, resume a session, kill/restart serve (RESILIENCY-14), drop the connection (reconnect), cancel mid-stream.

## New dependencies
- **Runtime**: `websockets>=12` (add to `pyproject.toml` `dependencies`).
- **Dev**: none beyond existing (`pytest`, `pytest-asyncio`, `anyio`, `hypothesis`).

## Notes for Code Generation
- Place `Transport` (abstract) + `ServeTransport`, `ChatService`, `Supervisor` under `caduceus/transport/`.
- Keep all `hermes serve` wire specifics behind `ServeTransport`; `ChatService`/`Supervisor` depend only on the abstract `Transport` + injected U2 `Registry`/`HealthChecker`/`Provisioner` (testability M-1).
- Exact JSON-RPC method names, session/cancel verbs, and auth header for `hermes serve` are finalized in **U3 Infrastructure Design / Build & Test** (same deferral convention as U2's sbx command lines).
