# U4 CLI / Daemon / Config — Deployment / Runtime Architecture

The full system runtime, now that U4 composes U1+U2+U3 into one deployable. Single local
host (WSL2 + Docker). No cloud, no staging/prod split.

## Full runtime view
```
 caduceus CLI (per-command)                    caduceus daemon (one process; `gateway start`)
 ┌───────────────┐   http/SSE (loopback)   ┌─────────────────────────────────────────────┐
 │ typer handlers│ ───────────────────────►│ Control API  127.0.0.1:9700                  │
 │ ControlAPIClnt│                          │   routes → AgentService(U2) / ChatService(U3)│
 └───────────────┘                          │            / ConfigService(U4)               │
                                            │ Supervisor(U3) 30s sweep                      │
                                            │ AI-Gateway(U1)  <bridge>:9701  ◄──────────┐   │
                                            └───────────────────────────────────────────┼───┘
                                                       │ Transport (ws)                  │ OpenAI /v1
                                                       ▼                                 │ (bearer)
                              agent sandbox (sbx/Docker): hermes serve :9119 ────────────┘
                                                       │ hermes LLM provider base_url = AI-Gateway
                                            upstream LLM (llama-swap 127.0.0.1:9292/v1)  ◄── AI-Gateway forwards
```

Text alternative: each `caduceus` command runs the CLI, which calls the daemon's loopback
Control API. The daemon hosts the Control API, the U1 AI-Gateway (on the bridge iface), the
U2 registry/agent services, the U3 chat/transport + Supervisor. Chat flows CLI→Control
API(SSE)→ChatService→Transport(ws)→agent `hermes serve`. The agent's hermes calls the
caduceus AI-Gateway for LLM, which forwards to the upstream llama-swap. Config edits flow
CLI→ConfigService→ConfigEditor→sandbox.

## Lifecycle
- `caduceus gateway start [-d]` → bootstrap config → acquire lock → build apps → run both listeners → Supervisor.start.
- `caduceus gateway stop` → signal pid → graceful stop → release lock.
- `caduceus gateway status` → pid/uptime/listeners/upstream health/agent count.

## Acceptance-criteria mapping (end-to-end, validated in Build & Test)
| AC | Path |
|---|---|
| AC-1 daemon up + AI-Gateway listening | `gateway start` → `gateway status` healthy |
| AC-2 create → configured → ls healthy | CLI→AgentService(U2)→sbx + AI-Gateway config |
| AC-3 chat streams + resumes session | CLI→ChatService(U3)→Transport; session persisted |
| AC-4 upstream down → graceful, daemon up | AI-Gateway(U1)/Supervisor(U3) degrade; clear CLI error |
| AC-5 register remote → uniform chat | AgentService.register(U2) + ChatService(U3) |
| AC-6 config edit verified in sandbox | ConfigService/ConfigEditor(U4) read-back + health |
| AC-7 rm tears down sandbox | AgentService.remove(U2) |

## Failure modes & responses
| Failure | Detection | Response |
|---|---|---|
| Daemon already running | lock held by live pid | `start` fails fast with pid |
| Stale lock (dead pid) | liveness check | reclaim + start |
| Upstream LLM down | U1 upstream check | `chat`/gateway clear error; daemon + Control API stay up (AC-4) |
| Agent serve down (local) | U3 Supervisor sweep | restart + back-off + circuit (U3) |
| Daemon not started | CLI `is_daemon_up` | friendly "run `caduceus gateway start`" |
| Missing upstream config | Settings.missing_required | prompt (TTY) or `ConfigError` (Q3) |
| Config apply fails | read-back/health verify | `ConfigResult.verified=false` + detail (AC-6) |

## Environments
- Single environment: the user's local host (WSL2 + Docker Engine), same as U1/U2/U3. Install via `pipx`; run `caduceus gateway start`.
