# U3 Transport & Chat — Code Generation Plan

**Unit**: U3. **Workspace root**: `/mnt/f/Workspace/Caduceus`. App code → root (never `aidlc-docs/`); summaries → `aidlc-docs/construction/u3-transport-chat/code/`.

## Unit context
- Implements **FR-C1..C4**, **RES-4** (timeouts/isolation/fail-fast/circuit), **RES-5** (supervision). Owns `caduceus/transport/`.
- **Depends on U2**: `Registry.get/set_session/list`, `AgentRecord` (carries `endpoint/serve_port/serve_auth/session_id/kind`), and (for local restart) the `Provisioner` + `HealthChecker`.
- **Buildable/testable in isolation**: the real `hermes serve` protocol is behind `ServeTransport` (lazy-imports `websockets`); unit tests drive a **FakeTransport** + fake health/restart callables — exactly mirroring U2's `FakeProvisioner` pattern. Real protocol is exercised in **Build & Test**.
- FD decisions in force: Q1 transparent session recreate · Q2 no caduceus turn-lock · Q3 supervisor defaults (30s/2/exp-backoff/3→circuit) · Q4 fail-fast · Q5 protocol-only health · Q6 cooperative cancel.

## Target files (application code)
```
caduceus/transport/__init__.py
caduceus/transport/events.py        # ChatEvent, ChatEventType + to_dict/from_dict + normalize_stream() terminal-guard relay
caduceus/transport/base.py          # Transport (ABC), TransportState/TransportKind, NotSupported, for_agent() factory
caduceus/transport/serve.py         # ServeTransport (websockets, lazy import): lazy open/reconnect, timeouts, cancel; wire codec isolated + Build&Test-flagged
caduceus/transport/chat.py          # ChatService: chat_stream (fail-fast gate → ensure-session → relay), _ensure_session (Q1)
caduceus/transport/supervisor.py    # Supervisor + AgentSupervisionState + CircuitState + backoff schedule (Q3); local-only restart (BR-A10)
pyproject.toml                      # add websockets>=12 to dependencies
tests/fakes.py                      # EXTEND: FakeTransport (scripted events), FakeRegistry, controllable health/restart callables
tests/unit/test_chat_events.py      # round-trip + terminal-guard
tests/unit/test_chat_service.py     # fail-fast gate, ensure/recreate session, relay, cancel
tests/unit/test_supervisor.py       # restart/backoff/circuit/reset, remote-no-restart, fault isolation
tests/pbt/test_transport_properties.py  # PBT-U3-1..7 incl. stateful Supervisor (RuleBasedStateMachine)
```

## Steps
- [x] **Step 1 — Events + relay**: `transport/events.py` — `ChatEventType` (token/message/error/done), `ChatEvent` (type/data/code + `to_dict`/`from_dict`), and `normalize_stream(raw_aiter)` that maps backend chunks → `ChatEvent` enforcing the **terminal-event invariant** (exactly one done XOR error; nothing after terminal). [BR-C5/C6; PBT-U3-1/2]
- [x] **Step 2 — Transport base + factory**: `transport/base.py` — `Transport` ABC (`open/close/chat_stream/health/get_config/set_config`), `TransportState`, `TransportKind`, `NotSupported`, `Transport.for_agent(rec)` → ServeTransport for v1. Shared relay reuse so all impls behave identically (FR-C3/C4). [BR-C7/C8]
- [x] **Step 3 — ServeTransport**: `transport/serve.py` — `websockets` client (lazy import), lazy `open` + reconnect-on-broken, per-call timeouts (`asyncio.wait_for`, Settings `Timeouts`), cooperative `cancel` (Q6), `health()` = protocol handshake only (no LLM; Q5). **Wire codec** (connect URL/auth frame/send/recv/parse/session+cancel verbs) isolated in small methods flagged "validated in Build & Test" (U3 Infra §validation). [BR-C10..C13; SEC-1]
- [x] **Step 4 — ChatService**: `transport/chat.py` — `chat_stream(name, message)`: resolve via Registry → **fail-fast gate** (failed/circuit/unhealthy → `error{agent_unavailable}`; transient `creating` → one short retry; Q4) → `_ensure_session` (resume; on rejection transparently recreate + persist new id; Q1) → relay events → persist session id via `Registry.set_session`. No turn-lock (Q2). [FR-C1/C2; BR-C1..C4/C14]
- [x] **Step 5 — Supervisor**: `transport/supervisor.py` — `AgentSupervisionState`, `CircuitState`, `BACKOFF=[5,15,45,120]`; `start/stop` (asyncio task), `_sweep()` (deep health per agent; local fail≥2 → restart via injected `restart`; exp backoff; 3 restart-fails → circuit open + `mark_failed`; healthy → reset; remote → probe/reconnect only, never restart). Fault-isolated loop. Injected interfaces: `list_agents`, `health_check`, `restart`, `mark_failed`. [RES-5; BR-S1..S7]
- [x] **Step 6 — Test doubles**: extend `tests/fakes.py` — `FakeTransport` (scripted `ChatEvent`/raw sequences, records cancel), `FakeRegistry` (get/set_session/list/upsert), controllable `fake_health`/`fake_restart` callables, `AcpLikeFake` (second transport for uniformity property).
- [x] **Step 7 — Unit tests**: `tests/unit/test_chat_events.py` (round-trip, terminal guard); `tests/unit/test_chat_service.py` (fail-fast gate, resume vs recreate + persistence, relay passthrough, cooperative cancel); `tests/unit/test_supervisor.py` (restart after 2 fails, backoff gate, circuit open→failed after 3, reset on healthy/manual, remote-never-restart, sweep swallows exceptions).
- [x] **Step 8 — Property tests**: `tests/pbt/test_transport_properties.py` — PBT-U3-1 single-terminal, -2 ChatEvent round-trip, -3 transport uniformity (Serve-like vs Acp-like over identical raw scripts), -4 session persistence, -5 fail-fast zero-tokens, -6 **stateful Supervisor** (`RuleBasedStateMachine` vs reference model: circuit/backoff/reset/remote invariants), -7 cooperative-cancel terminal+session-preserved. Seed logging via existing conftest profile (PBT-08).
- [x] **Step 9 — Dependency**: add `websockets>=12` to `pyproject.toml` `dependencies` (lazy-imported, so unit suite stays green even if not installed).
- [x] **Step 10 — Summaries**: `aidlc-docs/construction/u3-transport-chat/code/{business-logic-summary,api-layer-summary}.md`.
- [x] **Step 11 — Sanity run**: `pytest` in the venv (unit + PBT with FakeTransport; no real `hermes serve`/Docker). Expect U1+U2+U3 all green.

## Traceability
- FR-C1 chat/stream (Steps 1,3,4) · FR-C2 session resume (Step 4) · FR-C3 uniformity (Steps 1,2; PBT-U3-3) · FR-C4 acp-pluggable (Step 2) .
- RES-4 timeouts/fail-fast/isolation (Steps 3,4,5) · RES-5 supervision/circuit (Step 5).
- PBT-U3-1..7 (Steps 7,8) incl. stateful Supervisor (Step 8).

## Notes
- New runtime dep: **`websockets>=12`** only (lazy import; fallback to `httpx`+SSE possible if Build & Test shows that protocol — decided then).
- `ServeTransport` real impl written but unit-untested by design (protocol unconfirmed) — same convention as U2's `SbxProvisioner`; covered in Build & Test integration + RESILIENCY-14 fault injection.
- Supervisor takes injected callables (not concrete U2 classes) so U4 wires the real `Provisioner`/`Registry`/`HealthChecker` at composition time; keeps U3 decoupled + fully unit-testable.
- Build & Test validation items tracked in U3 Infra Design (wire protocol, auth handshake, session/cancel verbs, restart re-publish, fault injection).
