# Shared Infrastructure — Caduceus (local runtime)

Shared across all units. caduceus is a **local-first** tool: no cloud. "Infrastructure" = the local daemon process, its listeners, the Docker/sbx integration, host-reachability, state dir, and packaging.

## Empirical findings (spike on this host — WSL2 + Docker Engine 29.4.0)
| Test | Result | Implication |
|---|---|---|
| Container → host `0.0.0.0` port via `host.docker.internal` **with** `--add-host=host.docker.internal:host-gateway` | **REACHABLE** | works if we can pass add-host to the sandbox |
| Same **without** add-host | **UNREACHABLE** | native Engine (not Docker Desktop) has no default `host.docker.internal` |
| Container default gateway | **172.17.0.1** (docker bridge) = the host | **bridge gateway IP is reachable unconditionally** |

**Decision**: agents reach the AI-Gateway via an **`advertise_host`** that defaults to the **auto-detected docker bridge gateway IP** (e.g., `172.17.0.1`) — robust without add-host. `host.docker.internal` is supported as an alternative when the sandbox is created with `--add-host` (validated in U2).

## Listeners (Q3=A split)
| Listener | Bind | Default port | Reachable by | Auth |
|---|---|---|---|---|
| **Control API** | `127.0.0.1` | **9700** | local CLI only | none (loopback) |
| **AI-Gateway** | docker bridge IP (e.g., `172.17.0.1`), **not** broad `0.0.0.0` by default | **9701** | containers + host (not LAN) | per-agent bearer token |

Ports are configurable; chosen to avoid clashes with hermes serve (9119) and llama-swap (9292).

## Host paths
- State dir: **`~/.caduceus/`**
  - `state.json` (registry; atomic writes), `tokens/` or inline in state (agent bearer tokens, file perms 600), `logs/`, `config.toml` (optional overrides), `pid`/lock.
- hermes image build context: `images/hermes/` (in the repo).

## External dependencies (runtime)
- **Docker** Engine (bridge networking), **sbx** CLI, **hermes** (inside the image / remote), **upstream LLM** (llama-swap `localhost:9292/v1`).

## Configuration keys (caduceus Settings; env > file > default)
| Key | Default |
|---|---|
| `upstream_base_url` | `http://localhost:9292/v1` |
| `default_model` | `llamacpp/gemma-4-12b` |
| `control_bind` | `127.0.0.1:9700` |
| `aigateway_bind` | `<bridge-ip>:9701` (auto-detect bridge gw) |
| `aigateway_advertise_host` | auto-detected bridge gw IP (alt: `host.docker.internal`) |
| `state_dir` | `~/.caduceus` |
| timeouts | connect 10s / idle 120s / unary 300s |

## Packaging / deployment (RESILIENCY-04 decision)
- Single Python package, **pip/pipx-installable**; entry point `caduceus`.
- Deploy = direct install; **rollback = reinstall previous pinned version**.
- **CI = GitHub Actions** running pytest + Hypothesis with **seed logging** (PBT-08).

## Process / supervision model
- One daemon process per host (single-instance lock in `~/.caduceus`). Hosts both listeners + Supervisor (U3). `caduceus gateway start|stop|status`.
- Optional later: user-level systemd unit (out of scope v1; direct foreground/background run for now).
