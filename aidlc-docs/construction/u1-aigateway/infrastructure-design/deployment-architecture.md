# U1 AI-Gateway — Deployment Architecture (local)

## Runtime placement

```mermaid
flowchart LR
    subgraph HOST["host (WSL2)"]
        subgraph D["caduceus daemon (one process)"]
            CTRL["Control API<br/>127.0.0.1:9700"]
            AIGW["AI-Gateway<br/>172.17.0.1:9701"]
        end
        LS["Ollama<br/>127.0.0.1:11434"]
        CLI["caduceus CLI"]
    end
    subgraph BR["docker bridge 172.17.0.0/16"]
        AG["agent sandbox<br/>(hermes)"]
    end
    CLI -->|loopback| CTRL
    AG -->|"http://172.17.0.1:9701/v1 (bearer)"| AIGW
    AIGW -->|"http://localhost:11434/v1"| LS
    style D fill:#C8E6C9,stroke:#2E7D32,color:#000
    style AIGW fill:#FFA726,stroke:#E65100,color:#000
    style CTRL fill:#FFA726,stroke:#E65100,color:#000
    style LS fill:#BBDEFB,stroke:#1565C0,color:#000
    style AG fill:#BBDEFB,stroke:#1565C0,color:#000
```

Text alternative: On the host, the caduceus daemon runs one process with two listeners — Control API on 127.0.0.1:9700 (CLI only) and AI-Gateway on the docker bridge IP 172.17.0.1:9701 (reachable from sandboxes). An agent sandbox on the docker bridge calls the AI-Gateway at `http://172.17.0.1:9701/v1` with its bearer token; the AI-Gateway forwards to Ollama at `http://localhost:11434/v1`.

## Lifecycle
- `caduceus gateway start` → acquire `~/.caduceus` lock → detect bridge gw IP → bind both listeners → ready.
- `caduceus gateway status` → pid/uptime, listeners, upstream health, agent count, counters.
- `caduceus gateway stop` → graceful shutdown (drain streams, stop Supervisor, release lock).

## Failure modes (U1)
| Failure | Behavior |
|---|---|
| Upstream (Ollama) down | `/v1/*` → 502; `/v1/models` → minimal `[default]`; daemon stays up |
| Bridge IP undetectable | fall back to `host.docker.internal` advertise + `--add-host` (U2), or configured override |
| Port 9701 in use | startup error with remediation hint (configurable port) |

## Validation hooks (Build & Test)
- Integration: bring up daemon, hit AI-Gateway from a real sandbox, assert streamed completion via Ollama.
- Fault-injection (RESILIENCY-14): stop upstream, assert 502 + daemon liveness (AC-4).
