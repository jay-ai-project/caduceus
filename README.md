<div align="center">

<img src="assets/logo.png" alt="Caduceus" width="420" />

**A local-first gateway hub + CLI + Web UI for orchestrating sandboxed [hermes](https://hermes-agent.nousresearch.com/) agents.**

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue" />
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" />
  <img alt="Status" src="https://img.shields.io/badge/status-alpha-orange" />
</p>

</div>

---

Caduceus runs AI agents in isolated **Docker containers** (each running the hermes API
server), routes their LLM traffic through a single OpenAI-compatible gateway you control, and
gives you a CLI **and** a small web UI to provision, watch, and chat with them — with streaming
responses, thinking, and tool-call display.

- 🧪 **Containerized agents** — provision isolated hermes agents as Docker containers (optionally hardened with [gVisor](https://gvisor.dev/)), or register remote ones.
- 🔀 **Central AI-Gateway** — agents route their LLM calls through Caduceus to a configurable, OpenAI-compatible upstream (e.g. a local [Ollama](https://ollama.com/) at `http://localhost:11434/v1`, llama.cpp, LM Studio, vLLM, or a hosted API).
- 💬 **Streaming chat** — talk to any agent with session-persistent, streaming responses; see **thinking** and **tool calls** as they happen.
- 🖥️ **Web UI** — a dependency-free dashboard to see status, add agents (with live provisioning progress), and chat — served loopback-only.
- 🛠️ **Per-agent config** — edit a local agent's skills, tools, and persona ("soul").
- 🧭 **Agent dashboards** — each local agent's own hermes dashboard, reverse-proxied under the caduceus origin at `/agents/<name>/dashboard/` (per-agent login credentials via `agent dashboard-cred`).

> **Status:** alpha / under active development. Interfaces may change.

---

## Contents
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Web UI](#web-ui)
- [CLI](#cli)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Development](#development)
- [License](#license)

---

## Architecture

```
                         ┌──────────────── caduceus daemon ────────────────┐
   caduceus CLI ──HTTP──►│ Control API (127.0.0.1:9700) · Web UI + control │
   Web browser  ──HTTP──►│                                                 │
                         │ AI-Gateway (:9701, OpenAI /v1)                  │──HTTP──► upstream LLM
                         │ agent registry + supervisor                     │          (Ollama, llama.cpp, …)
                         └───────▲───────────────────────▲─────────────────┘
              caduceus ──HTTP/SSE─┘ (to each agent's       │ hermes agents call the AI-Gateway for their LLM
              (chat/stream/stop/    hermes API server)     │
               health)         ┌──────────────────────────┴──────────────┐
                       local Docker container (hermes API)   remote hermes API server (registered)
```

- **Control API** (`127.0.0.1:9700`, loopback) — serves the CLI, the Web UI (`/ui`), and agent control/chat endpoints.
- **AI-Gateway** (`:9701`, OpenAI-compatible) — the single endpoint every agent points at; forwards to your configured upstream LLM.
- **Local agents** run the **hermes API server** inside Docker containers, published on a host **loopback** port; **remote agents** are existing hermes API servers you register by URL. caduceus talks to both over one **HTTP/SSE** transport.

## Requirements

- **Python 3.11+**
- For **local containerized agents**: [Docker](https://www.docker.com/) Engine. Caduceus pulls the official [`nousresearch/hermes-agent`](https://hermes-agent.nousresearch.com/docs/user-guide/docker) image automatically on first `agent create` (it's large — ~3.8 GB — as it bundles the full agent toolchain). Optionally, [gVisor](https://gvisor.dev/) (`runsc`) for stronger sandboxing — see [`caduceus doctor`](#cli) and `gateway config --runtime`.
- An **OpenAI-compatible LLM endpoint** for the upstream (e.g. [Ollama](https://ollama.com/), llama.cpp server, LM Studio, vLLM, or a hosted API).

> Remote-only usage (registering existing hermes API servers) does not require Docker.

## Install

From source:

```bash
git clone <your-fork-url> caduceus
cd caduceus
python -m venv .venv && . .venv/bin/activate
pip install -e .
```

This installs the `caduceus` command.

## Quick start

```bash
# 1. Start the gateway. On first run it prompts for the upstream LLM
#    base URL and default model, and saves them to ~/.caduceus/config.toml
caduceus gateway start

# 2. Create a local containerized agent. Returns immediately and provisions in the
#    background (pulls the hermes image on first use); watch it become
#    running/healthy with `caduceus agent ls`. Add --wait to block until ready.
caduceus agent create my-agent

# 3. Chat with it (streaming). Once `agent ls` shows running/healthy, chat starts
#    instantly — the agent is warmed on create, so there's no first-turn cold start.
caduceus agent chat my-agent "Hello! Who are you?"

# 4. …or open the Web UI
#    http://127.0.0.1:9700/
```

Run the daemon detached with `caduceus gateway start -d`.

Stopping the gateway (`caduceus gateway stop`) leaves your agent containers running — only
`caduceus agent stop` / `caduceus agent rm` stop or remove them. When you start the daemon again it
reconnects to still-running agents (reconciled from `docker`), so they're immediately chat-able.

## Web UI

With the daemon running, open **<http://127.0.0.1:9700/>** (redirects to `/ui/`). The UI is a
single, dependency-free page that lets you:

- **Dashboard** — watch all agents with live lifecycle/health (hover a health badge for the cause) and connection info, pushed over a single `/api/events` SSE stream.
- **Add agent** — create a local agent (with live provisioning progress, optional model/image override) or register a remote endpoint.
- **Chat** — stream responses with collapsible **thinking** blocks and **tool-call** cards, a **Stop** button to cancel an in-flight turn, and lightweight markdown rendering (code blocks, inline code, bold, links); prior turns are best-effort loaded from the agent's session (local and remote).
- **Agent dashboards** — each local agent card links to the agent's own **hermes dashboard** (config, API keys, sessions), reverse-proxied same-origin at `/agents/<name>/dashboard/` — HTTP, SSE and WebSockets (embedded chat/terminal) all relay through the Control API. The dashboard has its own login: the **Creds** button (or `caduceus agent dashboard-cred <name>`) shows the per-agent username/password.

It is served **loopback-only with no authentication** — intended as a personal local tool. It is never exposed on the AI-Gateway port.

> **Agent-dashboard security note.** Dashboards are provisioned by default for new local agents
> (`--no-dashboard` to opt out) and are only reachable via host loopback. Inside the container the
> dashboard binds non-loopback, which engages hermes' mandatory auth gate — caduceus mints a
> per-agent password and injects it via container env (visible to anyone who can run
> `docker inspect`, i.e. you) and stores it in `~/.caduceus/state.json` alongside the agent's other
> secrets. Sessions don't survive an agent restart (re-login).

## CLI

```text
caduceus gateway start [-d]          Start the daemon (foreground, or -d to detach)
caduceus gateway stop                Stop the daemon (waits for it to exit)
caduceus gateway restart [-d]        Stop, then start the daemon
caduceus gateway status [--json]     Show daemon status (live upstream health + uptime)
caduceus gateway config [--get] [--upstream-url URL] [--model NAME] [--runtime runc|runsc] [--json]
                                     View / change upstream_base_url, default_model, container_runtime
caduceus doctor [--json]             Check upstream LLM reachability, Docker, hermes image,
                                     container runtime (gVisor), daemon

caduceus agent create <name> [--wait] [--model M] [--image I] [--no-dashboard] [--json]
                                     Provision a local containerized agent in the background
                                     (--wait blocks with live progress until ready;
                                      --model sets the agent's model, --image overrides its image;
                                      --no-dashboard skips the agent's web dashboard)
caduceus agent register <name> --endpoint <url> [--auth TOKEN]
                                     Register an existing remote hermes endpoint (--auth = the
                                     remote's own API-server key, if it already has one)
caduceus agent ls [--json]           List agents with lifecycle + health (+ health detail in JSON)
caduceus agent chat <name> [query]   Chat (streaming); omit query for an interactive REPL
caduceus agent stop|start <name>     Stop / start a local agent
caduceus agent rm <name>             Remove an agent (and its container, if local)
caduceus agent logs <name> [-f]      Stream a local agent's logs
caduceus agent dashboard-cred <name> [--json]
                                     Show the agent dashboard's URL + login credentials
caduceus agent config <name> [--get] [--remove-skill S]
        [--enable-tool T] [--disable-tool T] [--soul TEXT | --soul-file PATH]
        [--set key=value]            View / edit a local agent's config:
                                     soul → SOUL.md and skill removal apply on the next turn;
                                     tool/config changes restart the agent container.
                                     (Adding skills needs authored content — ask the agent to
                                      save a skill instead. `model`/`approvals` keys are
                                      caduceus-managed and cannot be --set.)
```

Most commands accept `--json` for scriptable output; exit codes are `0` (ok), `2` (usage), `1` (runtime/upstream error).

## Configuration

Config lives at `~/.caduceus/config.toml` (created interactively on first `gateway start`):

```toml
upstream_base_url = "http://localhost:11434/v1"   # your OpenAI-compatible LLM endpoint
default_model     = "your-model"                  # model used for the `default` alias
control_bind      = "127.0.0.1:9700"              # CLI + Web UI (loopback)
aigateway_bind    = "0.0.0.0:9701"                # agents reach this over the Docker bridge
container_runtime = "runc"                         # or "runsc" (gVisor) for stronger isolation
```

`upstream_base_url` and `default_model` are **required**; the daemon prompts for them if unset.

Change them later with `caduceus gateway config`:

```bash
caduceus gateway config                                   # show current values
caduceus gateway config --upstream-url http://localhost:11434/v1 --model llama3
caduceus gateway config --runtime runsc                   # use gVisor for new agent containers
```

> `--runtime runsc` requires gVisor installed and registered with Docker; run `caduceus doctor`
> to check. If `runsc` is configured but unavailable, `agent create` fails fast (no silent
> fallback to `runc`).

> **Network exposure**: the AI-Gateway binds `0.0.0.0:9701` by default — agent containers reach
> it over the Docker bridge, and *remote* agents reach it over your LAN. Every request requires a
> per-agent bearer token, but the port is visible on your network; caduceus assumes a trusted
> (home/lab) network. To restrict it to containers only, set `CADUCEUS_AIGATEWAY_BIND` (or
> `aigateway_bind`) to your Docker bridge IP, e.g. `172.17.0.1:9701` (auto-detected for the
> advertise address; remote agents then can't use the gateway). The Control API + Web UI stay
> loopback-only.

When the daemon is **running**, a change is applied **live** (no restart) and saved to
`config.toml`; when it is stopped, the file is edited directly and takes effect on the next
`gateway start`. (If `CADUCEUS_UPSTREAM_BASE_URL` / `CADUCEUS_DEFAULT_MODEL` are set in the
environment, they override `config.toml` on restart — the command warns when this applies.)
All values can also be supplied via `CADUCEUS_*` environment variables (e.g. `CADUCEUS_CONTROL_BIND`).

## How it works

Each agent's hermes config points its LLM provider at the Caduceus **AI-Gateway** instead of a
provider directly. The AI-Gateway authenticates the call (per-agent token), rewrites the
`default` model alias to your configured model, and forwards the request to your upstream
LLM — so you swap models or providers in one place, and every agent follows.

Every agent — local Docker container or remote — runs the **hermes API server**
(`hermes gateway run`), and Caduceus drives it over one **HTTP/SSE** transport: it chats via
the persistent Sessions API (`/api/sessions/{id}/chat/stream`), stops turns via the Runs API,
reads history from `/messages`, and checks liveness with `/health`. That single SSE stream is
how Caduceus surfaces streaming output, thinking, and tool calls. Local agent containers
publish their API server on a host **loopback** port (bearer-authenticated); sessions are
persisted per agent and transparently resumed. Container isolation uses `runc` by default, or
`runsc` (gVisor) when configured.

Local agents run the **official `nousresearch/hermes-agent` image** (pinned to a version tag),
which ships the full agent toolchain — Python, **Node + Playwright/Chromium**, `ffmpeg`, `git`,
`ripgrep`, the Docker CLI, `curl`/`wget`, and more — so agents can do web fetch, browser
automation, and code execution out of the box. Storage is split: the agent's config, memory,
and sessions live in `HERMES_HOME` (**`/opt/data`**) on the container's anonymous volume — they
survive stop/start but are wiped on `agent rm`. The agent's **working directory**
(`/opt/data/workspace`) is bind-mounted to the host at `~/.caduceus/agents/<agent>/workspace`,
so files the agent produces persist even across remove + re-create. The container runs as your
host UID/GID, keeping that workspace writable from both sides.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # unit + property-based (Hypothesis) tests
```

This project was built using an AI-DLC (AI-Driven Development Life Cycle) workflow; the
generated requirements, design, and per-unit artifacts live under [`aidlc-docs/`](aidlc-docs/).

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

## Acknowledgements

- [hermes](https://hermes-agent.nousresearch.com/) — the agent runtime Caduceus orchestrates (via its API server).
- [Docker](https://www.docker.com/) — container runtime for local agents; optionally [gVisor](https://gvisor.dev/) (`runsc`) for stronger isolation.
