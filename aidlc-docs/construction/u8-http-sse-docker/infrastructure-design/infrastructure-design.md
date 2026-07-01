# U8 Infrastructure Design (LIGHT) — HTTP/SSE + Docker Runtime

Local-first tool; no cloud. This LIGHT pass records the **deployment-model change**
(sbx→Docker) and the **new inbound network path**. Decisions are inline (requirements + FD +
spike resolved them).

## What changes vs U1–U7
- **Runtime**: Docker Sandboxes (`sbx`, microVM) → **plain Docker containers** (`docker` CLI).
- **Network directions**: previously only *outbound* (agent→AI-Gateway) mattered because ACP
  was stdio. Now there are **two**:
  1. **Outbound** (agent → caduceus AI-Gateway) — **unchanged**: Docker default-bridge gateway
     IP (e.g. `172.17.0.1:9701`) reachable from the container unconditionally.
  2. **Inbound** (caduceus → agent's hermes API server) — **NEW**: the container publishes its
     `8642` to a host **loopback** port; caduceus connects over HTTP/SSE.
- **Isolation**: microVM → `runc` (default) with optional **`runsc`/gVisor** for near-microVM
  syscall isolation (opt-in).

## Agent container run spec
```
docker run -d \
  --name cad-<name> \
  -p 127.0.0.1::8642            # Docker-assigned ephemeral host port (loopback only)
  [--runtime runsc]             # only when configured AND available (else runc, the default)
  -v <workspace_host>:<workspace_host> \
  -e API_SERVER_ENABLED=true \
  -e API_SERVER_KEY=<agent_token> \
  -e API_SERVER_HOST=0.0.0.0    # inside the container only; not host-exposed beyond loopback
  -e API_SERVER_PORT=8642 \
  -e OPENAI_API_KEY=<agent_token>   # outbound LLM auth to the AI-Gateway (existing)
  <caduceus/hermes:pinned>
# entrypoint: hermes gateway run   (API-server platform enabled by the env above)
```
- **Port allocation (FD D3)**: let Docker assign the host port (`-p 127.0.0.1::8642`), then
  read it back via `docker inspect`/`docker port` → `AgentRecord.host_port` →
  `endpoint = http://127.0.0.1:<host_port>`. Avoids selection races; survives restarts via
  boot reconcile.
- **`--restart no`**: caduceus's Supervisor owns restart policy (BR-O3), not Docker.

## Network trust boundary (security — advisory, Q9)
| Path | Bind/route | Exposure | Auth |
|---|---|---|---|
| caduceus → agent (inbound, NEW) | host `127.0.0.1:<host_port>` → container `:8642` | **loopback only** (never LAN) | `Authorization: Bearer <token>` = `API_SERVER_KEY` |
| agent → AI-Gateway (outbound) | bridge gw IP `:9701` | containers + host | per-agent bearer (existing) |
| Control API / Web UI | `127.0.0.1:9700` | loopback | none (loopback) |

## Container runtime selection (gVisor)
- Config `container_runtime` ∈ {`runc` (default), `runsc`}. Passed as `docker run --runtime`.
- **Availability = spawn-time, fail-fast** (BR-R2): if `runsc` configured but Docker has no
  such runtime, `docker run` fails → caduceus raises actionable guidance; **no silent runc**.
- **gVisor is a user prerequisite** (never installed by caduceus). `caduceus doctor` detects
  presence (`docker info` runtimes / `runsc` on PATH) and prints install guidance (Q3).

## Image build/deploy
- `docker build images/hermes/` → pinned tag; used directly by `docker run`.
- **Removed**: `docker save | sbx template load` bridging (Finding D obsolete — no separate
  sbx image store).
- Dockerfile: swap the `[acp]` extra for the extra shipping the **gateway + aiohttp**; ensure
  `hermes gateway run` exists; keep pinned hermes version/git-ref (SECURITY-10, no `latest`).

## Health & lifecycle over Docker
- **Health**: HTTP `GET /health` (shallow, no LLM spend); live `docker inspect` status for
  reconcile/lifecycle (not the health signal). Probed **live per request** for `agent ls`
  (no cache — NFR-U8-P1).
- **Boot reconcile** (U7 preserved): daemon start → `docker ps` for `cad-*` → reattach running
  containers (recompute host_port/endpoint) → `running`; absent → `stopped`.
- **`gateway stop`** leaves containers running (U7 decoupling); Supervisor auto-restarts only
  `running` agents.

## External dependencies (runtime) — updated
- **Docker** Engine (bridge networking + `-p` loopback publish; runtimes `runc`, optional
  `runsc`). **`sbx` removed.** hermes (inside the image / remote). Upstream LLM (Ollama).

## Config keys added/removed (Settings)
- **Added**: `container_runtime` (env `CADUCEUS_CONTAINER_RUNTIME`, file `container_runtime`,
  default `runc`).
- **Unchanged**: `upstream_base_url`, `default_model`, `control_bind`, `aigateway_bind`,
  `aigateway_advertise_host`, `upstream_auth`, timeouts, `state_dir`.
- **Effectively removed**: sbx-related assumptions; `serve_port`/`serve_auth` on AgentRecord.

## Deferred / out of scope (unchanged posture)
- No cloud IaC, no systemd unit, no off-host exposure. Performance not a gate.
