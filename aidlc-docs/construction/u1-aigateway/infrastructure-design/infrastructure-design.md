# U1 AI-Gateway — Infrastructure Design

Maps U1 logical components to the local runtime. See [shared-infrastructure.md](../../shared-infrastructure.md) for project-wide binds/ports/paths.

## AI-Gateway listener
- **Process**: runs inside the caduceus daemon (not a separate process), as a FastAPI app on uvicorn.
- **Bind**: docker **bridge gateway IP** (auto-detected, e.g. `172.17.0.1`) : **9701** — reachable from sandboxes + host, but **not** the broader LAN. (Override to `0.0.0.0` only if explicitly desired.)
- **Advertise**: agents are configured with provider `base_url = http://<advertise_host>:9701/v1`, where `advertise_host` defaults to the bridge gateway IP (spike-proven reachable). `host.docker.internal` usable when the sandbox is created with `--add-host` (decided in U2).
- **Auth**: per-agent bearer token (BR-1); tokens minted by U2 at agent creation, stored under `~/.caduceus` (perm 600), injected into the agent's hermes provider `api_key`.

## Component → infra mapping
| Logical component | Infra realization |
|---|---|
| AIGatewayApp | FastAPI router mounted in the daemon's uvicorn (separate listener/port from Control API) |
| UpstreamClient | shared `httpx.AsyncClient` (keep-alive pool) → `upstream_base_url` |
| StreamPump | Starlette `StreamingResponse` (SSE) |
| MetricsCounter | in-process counters (no external metrics backend — N/A for local tool) |
| token→agent map | read from Registry (U2) in memory; backing store `~/.caduceus/state.json` |

## Networking topology (text)
- Agent (container) → `http://172.17.0.1:9701/v1` (bridge gw) → AI-Gateway (daemon) → `http://localhost:9292/v1` (llama-swap on host).
- Control API on `127.0.0.1:9700` is **not** reachable from containers (loopback) — control/data plane separation (Q3=A).

## Storage / messaging
- **Storage**: none beyond the shared `state.json` (token map). No DB, no queue, no cache (transparent proxy).
- **Messaging**: none.

## Monitoring
- Structured logs to `~/.caduceus/logs/`; counters via `gateway status`. No external observability stack (N/A, personal tool — RESILIENCY-05 scaled).

## Security posture (baseline; Security ext OFF)
- Bind scoped to bridge IP (limits exposure to containers+host).
- Bearer-token gate on all `/v1/*`.
- Token redaction in logs.
- Residual risk accepted: any local process/container can attempt the AI-Gateway (token-gated). Acceptable for a personal tool; can tighten later.
