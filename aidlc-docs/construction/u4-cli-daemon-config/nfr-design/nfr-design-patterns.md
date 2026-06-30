# U4 CLI / Daemon / Config — NFR Design Patterns

Realizes U4's NFRs. Project-wide resiliency process decisions (CI / rollback / resiliency
testing / incident) were settled at U1 NFR Design and inherited. Patterns derive from the
locked FD decisions (Q1–Q6).

## Architecture / maintainability patterns
| Pattern | Application | Traces |
|---|---|---|
| **Composition Root + Dependency Injection** | `GatewayService.start` is the single place that constructs and wires U1/U2/U3, injecting U3's callables (`list_agents`/`health_check`/`restart`/`mark_failed`) and binding U1 `token_lookup`→`Registry.token_lookup`. Units stay decoupled. | BR-W1/W2; M-1/M-4 |
| **Thin Adapter (Humble Object)** | CLI handlers and Control API routes carry no business logic — they translate input→service call→render. Logic lives in U1/U2/U3 services + the pure config reducer. | M-1 |
| **Pure function core** | `apply_change(snapshot, change)` is pure (no I/O) → idempotent/order-independent; all sandbox I/O is at the edges (ConfigEditor). | BR-E3; M-2; PBT-U4-2 |
| **Strategy (pluggable, table-driven)** | `CHANGE_KIND_STRATEGY: kind→ReloadStrategy` resolves how a config change is applied (v1 all `hot_reload`); the single seam to later force `restart_serve` per kind. | BR-E4/E5; Q2; PBT-U4-5 |
| **DTO + projection** | Service models → API DTOs; `AgentView` projects `AgentRecord`+`HealthStatus` and **strips secrets** (`token`/`serve_auth`). | BR-O3; SEC-2; PBT-U4-3 |

## Resilience / lifecycle patterns (RES-4/RES-5, RESILIENCY-10)
| Pattern | Application | Traces |
|---|---|---|
| **Single-instance lock** | pid/lock file in `~/.caduceus`; liveness check reclaims a stale lock; second start fails fast. | R-1; BR-G3 |
| **Graceful shutdown** | SIGINT/SIGTERM → `stop()`: Supervisor.stop → drain in-flight → close transports → release lock; idempotent. | R-2/R-3; BR-G5 |
| **Daemonize (opt-in)** | `-d` → `fork`/`setsid`, redirect stdio → `~/.caduceus/logs/daemon.log`; foreground default keeps it optional. | BR-G2; Q1 |
| **Bulkhead / split listeners** | Control API (loopback) and AI-Gateway (bridge) are independent async servers in one process; neither starves the other. | R-5; BR-G4 |
| **Error-to-response boundary** | Control API converts service exceptions to JSON + status (`ProxyError.to_openai`); a single op failure never crashes the daemon. | R-4 |
| **Config bootstrap (precedence resolver)** | env > `config.toml` > default; interactive prompt only on foreground TTY, else `ConfigError`. | R-?/U-3; BR-G6; Q3 |
| **Verify-after-write** | config apply → read-back + post-reload shallow health → `ConfigResult.verified`. | BR-E6; Q4; AC-6 |

## Usability / output patterns (NFR-1, Q6)
- **Dual renderer**: human (tables/sentences) default, `--json` for scripts; one renderer per command.
- **Total exit-code mapping**: success→0, usage/validation→2, runtime/upstream/daemon→1 (no unmapped outcome; PBT-U4-6).
- **Actionable errors**: each error includes the recovery step (daemon-down, upstream-unset, agent-unavailable).
- **SSE pass-through**: `chat`/`logs` stream as they arrive (no buffering), Ctrl-C → cooperative cancel (U3).

## Security patterns (NFR-6; baseline)
- **Loopback confinement**: control plane bound to `127.0.0.1` only; never a routable iface.
- **Secret hygiene**: DTO projection omits secrets; redacting logger on all daemon logs; `config.toml` perms 600.

## Observability
- Structured (redacted) daemon log file; lifecycle events logged (start/stop/lock/bootstrap/config-apply). `agent logs` surfaces hermes logs via U2 Provisioner. Metrics/traces/dashboards N/A (personal tool).

## Resolved project-wide decisions (inherited from U1 NFR Design)
- CI = GitHub Actions (pytest + Hypothesis, seed-logged); rollback = reinstall previous pinned version; deploy = direct install (`pipx`); resiliency testing = lightweight fault injection (here: daemon up/down, upstream down → graceful CLI errors, lock contention, config-apply failure); incident = log-based triage + restart.
