# U4 CLI / Daemon / Config — Infrastructure Design

U4 is the **daemon itself** + the CLI. It consolidates the local runtime defined in
`construction/shared-infrastructure.md` (which all units share) and adds the process model,
on-disk layout, packaging, and entry point. caduceus is **local-first** — no cloud.
**No infrastructure questions** — listeners/network/paths/packaging are already locked.

## Process model
- **One daemon process per host** (`caduceus gateway start`), hosting **two ASGI listeners** + the U3 Supervisor in one asyncio loop.
- **Foreground default**; `-d/--daemon` detaches a background child (`fork`+`setsid`, stdio → `~/.caduceus/logs/daemon.log`), parent prints pid and exits.
- **Single instance**: pid/lock file gates a second start; stale (dead-pid) lock reclaimed.
- **CLI** is a separate short-lived process per command, talking to the daemon over loopback HTTP.

## Listeners (App Design Q3 split; from shared-infrastructure)
| Listener | Bind | Default port | Reachable by | Auth |
|---|---|---|---|---|
| Control API | `127.0.0.1` | 9700 | local CLI only | none (loopback) |
| AI-Gateway (U1) | docker bridge IP (e.g. `172.17.0.1`) | 9701 | sandboxes + host | per-agent bearer |

Both served by `uvicorn` in the one daemon process (two `Server` instances on one loop).

## Host paths (`~/.caduceus/`)
| Path | Purpose | Perms |
|---|---|---|
| `state.json` | U2 registry (atomic writes) | 600 |
| `config.toml` | U4 persisted settings (upstream/model/binds) — written by config bootstrap (Q3) | 600 |
| `caduceus.pid` (+ lock) | single-instance guard | 644 / advisory lock |
| `logs/daemon.log` | daemonized stdout/stderr + structured daemon log | 600 |
| (tokens inline in state.json) | per-agent bearer + serve_auth | 600 |
| dir `~/.caduceus/` | container | 700 |

## Configuration precedence (Settings)
`env > ~/.caduceus/config.toml > built-in default`. Required (`upstream_base_url`, `default_model`)
have **no default** — bootstrap prompts on foreground TTY and persists to `config.toml`;
non-interactive → `ConfigError` with guidance.

## Packaging / deployment (RESILIENCY-04, inherited)
- Single `caduceus` package; **pip/pipx-installable**; **console script** `caduceus = "caduceus.cli.app:app"` registered in `pyproject.toml` (this unit).
- New runtime dep: **`typer>=0.12`** (CLI). `fastapi`/`uvicorn`/`httpx`/`websockets` already present.
- Deploy = direct install; rollback = reinstall previous pinned version; CI = GitHub Actions (pytest + Hypothesis, seed-logged).

## Daemonization details (WSL2/Linux target)
- `-d`: double `fork` + `os.setsid`, `chdir('/')` (or state dir), redirect stdio to `logs/daemon.log`; write pid; child runs the asyncio servers. (Non-goal: Windows-native service; systemd unit is a documented later option.)
- Signal handling: SIGINT/SIGTERM → graceful `stop()` (Supervisor stop → drain → release lock).

## Security
- Control plane never leaves loopback; AI-Gateway exposure unchanged from U1 (bridge iface, bearer). Secrets at rest 600; never logged/printed (redaction + DTO projection).

## Build & Test validation items (U4-specific)
1. **Daemonize on WSL2**: `-d` detaches cleanly, logs to file, survives terminal close; `gateway stop` terminates it; lock reclaim after a kill -9.
2. **Console script**: `pipx install .` exposes `caduceus`; `caduceus gateway start` boots both listeners (AC-1).
3. **Config bootstrap**: first-run prompt writes `config.toml`; subsequent starts reuse it; env overrides file.
4. **End-to-end (AC-2..AC-7)**: create → ls healthy → chat streams + resumes → register remote → config edit verified in sandbox (AC-6) → rm tears down.
5. **Config reload mechanism**: confirm hermes hot-reload vs restart per change kind (feeds CHANGE_KIND_STRATEGY); confirm in-sandbox config paths.
6. **Graceful degradation (AC-4)**: upstream down → `chat` clear error, daemon stays up, `agent ls` shows unhealthy.
