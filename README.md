# Caduceus

> A local-first **gateway hub + CLI + Web UI** for orchestrating sandboxed
> [hermes](https://hermes-agent.nousresearch.com/) agents.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue" />
  <img alt="Status" src="https://img.shields.io/badge/status-alpha-orange" />
</p>

Caduceus runs AI agents in isolated [Docker sandboxes](https://docs.docker.com/ai/sandboxes/),
routes their LLM traffic through a single OpenAI-compatible gateway you control, and gives
you a CLI **and** a small web UI to provision, watch, and chat with them — with streaming
responses, thinking, and tool-call display.

- 🧪 **Sandboxed agents** — provision isolated hermes agents in `sbx` Docker sandboxes, or register remote ones.
- 🔀 **Central AI-Gateway** — agents route their LLM calls through Caduceus to a configurable, OpenAI-compatible upstream (e.g. a local [Ollama](https://ollama.com/) at `http://localhost:11434/v1`, llama.cpp, LM Studio, vLLM, or a hosted API).
- 💬 **Streaming chat** — talk to any agent with session-persistent, streaming responses; see **thinking** and **tool calls** as they happen.
- 🖥️ **Web UI** — a dependency-free dashboard to see status, add agents (with live provisioning progress), and chat — served loopback-only.
- 🛠️ **Per-agent config** — edit a local agent's skills, tools, and persona ("soul").

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
                         ┌────────────────────────── caduceus daemon ──────────────────────────┐
  caduceus CLI ──HTTP──> │  Control API (127.0.0.1:9700)  ── Web UI + agent control            │
  Web browser  ──HTTP──> │                                                                      │
                         │  AI-Gateway (:9701, OpenAI /v1) ───────────────────► upstream LLM    │
                         │  agent registry + supervisor                          (Ollama, …)    │
                         └───────────▲──────────────────────────────────────────────────────────┘
                                     │ hermes agents call the AI-Gateway for their LLM
                  ┌──────────────────┴───────────────────┐
            local sbx sandbox (hermes)            remote hermes (registered)
```

- **Control API** (`127.0.0.1:9700`, loopback) — serves the CLI, the Web UI (`/ui`), and agent control/chat endpoints.
- **AI-Gateway** (`:9701`, OpenAI-compatible) — the single endpoint every agent points at; forwards to your configured upstream LLM.
- **Local agents** run hermes inside `sbx` Docker sandboxes; **remote agents** are existing hermes endpoints you register by URL.

## Requirements

- **Python 3.11+**
- For **local sandboxed agents**: [Docker](https://www.docker.com/) and the **`sbx`** ([Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)) CLI. Caduceus builds/loads the bundled hermes image automatically on first `agent create`.
- An **OpenAI-compatible LLM endpoint** for the upstream (e.g. [Ollama](https://ollama.com/), llama.cpp server, LM Studio, vLLM, or a hosted API).

> Remote-only usage (registering existing hermes endpoints) does not require Docker/`sbx`.

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

# 2. Create a local sandboxed agent (builds the hermes image on first use,
#    streams live provisioning progress)
caduceus agent create my-agent

# 3. Chat with it (streaming)
caduceus agent chat my-agent "Hello! Who are you?"

# 4. …or open the Web UI
#    http://127.0.0.1:9700/
```

Run the daemon detached with `caduceus gateway start -d`.

## Web UI

With the daemon running, open **<http://127.0.0.1:9700/>** (redirects to `/ui/`). The UI is a
single, dependency-free page that lets you:

- **Dashboard** — watch all agents with live lifecycle/health and connection info (auto-refreshing).
- **Add agent** — create a local sandbox (with live provisioning progress) or register a remote endpoint.
- **Chat** — stream responses with collapsible **thinking** blocks and **tool-call** cards; prior turns are best-effort loaded from the agent's session.

It is served **loopback-only with no authentication** — intended as a personal local tool. It is never exposed on the AI-Gateway port.

## CLI

```text
caduceus gateway start [-d]          Start the daemon (foreground, or -d to detach)
caduceus gateway stop                Signal the daemon to stop
caduceus gateway status [--json]     Show daemon status

caduceus agent create <name> [--model M] [--upstream-url U] [--image I] [--json]
                                     Provision a local sandboxed agent (live progress)
caduceus agent register <name> --endpoint <url> [--auth TOKEN]
                                     Register an existing remote hermes endpoint
caduceus agent ls [--json]           List agents with lifecycle + health
caduceus agent chat <name> [query]   Chat (streaming); omit query for an interactive REPL
caduceus agent stop|start <name>     Stop / start a local agent
caduceus agent rm <name> [--force]   Remove an agent (and its sandbox, if local)
caduceus agent logs <name> [-f]      Stream a local agent's logs
caduceus agent config <name> [--get] [--add-skill S] [--remove-skill S]
        [--enable-tool T] [--disable-tool T] [--soul TEXT | --soul-file PATH]
        [--set key=value]            View / edit a local agent's skills, tools, persona
```

Most commands accept `--json` for scriptable output; exit codes are `0` (ok), `2` (usage), `1` (runtime/upstream error).

## Configuration

Config lives at `~/.caduceus/config.toml` (created interactively on first `gateway start`):

```toml
upstream_base_url = "http://localhost:11434/v1"   # your OpenAI-compatible LLM endpoint
default_model     = "your-model"                  # model used for the `default` alias
control_bind      = "127.0.0.1:9700"              # CLI + Web UI (loopback)
aigateway_bind    = "0.0.0.0:9701"                # agents reach this over the Docker bridge
```

`upstream_base_url` and `default_model` are **required**; the daemon prompts for them if unset.
All values can also be supplied via `CADUCEUS_*` environment variables (e.g. `CADUCEUS_CONTROL_BIND`).

## How it works

Each agent's hermes config points its LLM provider at the Caduceus **AI-Gateway** instead of a
provider directly. The AI-Gateway authenticates the call (per-agent token), rewrites the
`default` model alias to your configured model, and forwards the request to your upstream
LLM — so you swap models or providers in one place, and every agent follows.

Local agents are driven over the **Agent Client Protocol** (`hermes acp`, stdio JSON-RPC) via
`sbx exec`, which is how Caduceus surfaces streaming output, thinking, and tool calls. Sessions
are persisted per agent and transparently resumed.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # unit + property-based (Hypothesis) tests
```

This project was built using an AI-DLC (AI-Driven Development Life Cycle) workflow; the
generated requirements, design, and per-unit artifacts live under [`aidlc-docs/`](aidlc-docs/).

## License

See [LICENSE](LICENSE).

## Acknowledgements

- [hermes](https://hermes-agent.nousresearch.com/) — the agent runtime Caduceus orchestrates.
- [Docker Sandboxes (`sbx`)](https://docs.docker.com/ai/sandboxes/) — isolated environments for local agents.
