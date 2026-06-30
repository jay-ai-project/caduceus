# U3 Transport & Chat — Infrastructure Design (LIGHT)

Per the Units plan, U3 infrastructure is **light**: U3 introduces **no new image, no new listener, no
new storage**. It is a **client** of the agent's `hermes serve` and an in-daemon background task.
Everything reuses `construction/shared-infrastructure.md` and the U2 agent runtime. **No infrastructure
questions** — networking, process model, and packaging are already locked.

## What U3 adds to the running system
| Concern | U3 contribution | Reuses |
|---|---|---|
| New process | **none** — `ChatService` + `Supervisor` run **inside** the existing caduceus daemon process | shared-infra "one daemon per host" |
| New listener | **none** — U3 is an outbound client; chat is exposed via the existing Control API SSE route (U4) | Control API `127.0.0.1:9700` |
| New storage | **none** — only `AgentRecord.session_id` persisted via the U2 Registry (`~/.caduceus/state.json`) | U2 state store |
| New runtime dep | `websockets>=12` (client) | — |
| New image | **none** | U2 hermes image |

## Network path (transport → agent)
**Local agent (sbx):**
```
caduceus daemon (host)                      agent sandbox (Docker)
  ServeTransport ──ws──> 127.0.0.1:<host_port> ──(sbx publish)──> 0.0.0.0:9119  hermes serve
                          ▲ AgentRecord.serve_port (published host port from `sbx ports`)
   auth: HERMES_SERVE_PASSWORD = AgentRecord.serve_auth
```
- The daemon connects to the **published host port** (loopback/host side) that U2's `Provisioner.start_serve` obtained; it does **not** need to be inside the Docker network.
- In-sandbox serve port is fixed (`9119`); the **host** port is dynamic per agent (stored in `serve_port`).

**Remote agent (registered):**
```
caduceus daemon ──ws/https──> AgentRecord.endpoint   (user-provided URL; auth via registered token/serve_auth)
```
- No restart capability (BR-A10); transport connect/reconnect only.

## Process / supervision placement
- **Supervisor** is an `asyncio` background task started by the daemon on `gateway start` and cancelled on `gateway stop` (graceful, RES-4). It shares the daemon's event loop — no separate process/cron.
- **Local restart** uses the **U2 `Provisioner`** (`sbx exec` to relaunch `hermes serve`, re-publish port, update `serve_port`). U3 does not shell out to `sbx` itself — it calls the injected interface.

## Security / exposure (no change)
- U3 opens **no inbound port**. Outbound only, to loopback (local) or the registered endpoint (remote).
- `serve_auth` carried in the transport auth handshake; redacted in logs (shared logging filter).

## Build & Test validation items (deferred, U3-specific)
1. **Wire protocol**: confirm `hermes serve` transport = JSON-RPC over WebSocket (then keep `websockets`) **or** HTTP+SSE (then fall back to the already-present `httpx`, drop `websockets`).
2. **Auth header/handshake** exact form for `HERMES_SERVE_PASSWORD`.
3. **Session verbs**: how a session is created, resumed, and identified in the stream (maps to `_ensure_session` + `session_id` persistence).
4. **Cancel verb**: best-effort cancel mechanism for cooperative cancellation (Q6).
5. **Restart re-publish**: after `Provisioner` restarts serve, confirm a new host port is obtained and `serve_port` updated; transport reconnects.
6. **Fault injection (RESILIENCY-14)**: kill serve → assert restart/back-off/circuit; drop connection mid-stream → assert reconnect; stall backend → assert idle timeout → `error{code=timeout}`.

## Packaging
- No change: U3 modules ship in the same `caduceus` package; only `pyproject.toml` gains `websockets>=12` (pending item 1 above).
