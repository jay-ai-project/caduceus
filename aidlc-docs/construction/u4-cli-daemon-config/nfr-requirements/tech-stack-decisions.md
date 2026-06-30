# U4 CLI / Daemon / Config — Tech Stack Decisions

Inherits the global stack (Python 3.11+, `asyncio`, FastAPI + `uvicorn` + `httpx` from U1).
U4 adds **one** runtime dependency: `typer` for the CLI. The console entry point `caduceus`
is registered here (was deferred from U1).

| Concern | Choice | Rationale |
|---|---|---|
| CLI framework | **`typer`** (on Click) | declarative commands/options, help + completion, fits the `agent …`/`gateway …` surface (Stack Q3=A earmarked typer for U4) |
| Control API server | FastAPI app on **`uvicorn`** (already a dep) | reuse U1’s ASGI stack; split listeners run two uvicorn servers in one process |
| Control API client | **`httpx`** (already a dep) | unary + SSE consumption for `chat`/`logs`; loopback |
| Daemonization (`-d`) | stdlib `os.fork`/`setsid` + redirect to `~/.caduceus/logs/` (POSIX/WSL2) | no extra dep; foreground default keeps it optional |
| Single-instance lock | stdlib (`os`/`fcntl` advisory lock or pid-file with liveness check) | no dep; consistent with `~/.caduceus` hygiene |
| Config file | **TOML** read via stdlib `tomllib` (3.11+); write via a tiny serializer | stdlib-only read; `config.toml` per shared-infrastructure |
| Settings | extend existing `caduceus/common/settings.py` (`from_env` → add file layer) | env > file > default already designed |
| Models/DTOs | dataclasses with explicit `to_dict`/`from_dict` | consistent with U1/U2/U3; PBT round-trip |
| Signal handling | stdlib `signal` / `asyncio` loop signal handlers | graceful stop |

## Why not alternatives
- **argparse/click directly**: typer gives the same with less boilerplate and good help; already the planned choice.
- **python-daemon / systemd as the only option**: kept optional — foreground default + simple `-d` fork covers the personal-tool need without a hard dependency; systemd remains a documented later option.
- **pydantic models for DTOs**: dataclasses match the rest of the codebase and keep PBT round-trips simple; FastAPI still validates request bodies at the route boundary.

## Testing (PBT-09 satisfied globally)
- **Unit**: `pytest` with an in-process ASGI client (`httpx.ASGITransport`) over the Control API + fakes for AgentService/ChatService/ConfigEditor; CLI handlers tested via the typer `CliRunner` with a fake ControlAPIClient.
- **Property**: **Hypothesis** — DTO round-trips, the pure `apply_change` reducer (idempotent/order-independent), no-secret projection, remote read-only, reload-strategy + exit-code totality. Seed logging via existing `conftest.py`.
- **Integration** (Build & Test): real `caduceus gateway start` → end-to-end CLI→daemon→agent→AI-Gateway→upstream; real config edit verified in a sandbox (AC-6); daemonize/stop/lock behavior; RESILIENCY-14 (upstream down, agent down → graceful).

## New dependencies
- **Runtime**: `typer>=0.12` (+ console script `caduceus`). `uvicorn`/`httpx`/`fastapi` already present.
- **Dev**: none beyond existing (`pytest`, `pytest-asyncio`, `anyio`, `hypothesis`).

## Notes for Code Generation
- Register `[project.scripts] caduceus = "caduceus.cli.app:app"` (or `__main__`) in `pyproject.toml`.
- Keep CLI handlers + Control API routes **thin** (delegate to services) for testability (M-1).
- Extend `Settings` with a TOML file layer (`from_env_and_file`) preserving env > file > default.
- Exact hermes config-reload mechanism + in-sandbox config paths validated in Build & Test (config edit).
