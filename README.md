# Caduceus

A local-first **gateway hub + CLI** for orchestrating sandboxed [hermes](https://) agents.

Caduceus:
- provisions isolated hermes agents in `sbx` Docker sandboxes (or registers remote ones),
- acts as a central **AI-Gateway** (OpenAI-compatible) so agents route their LLM calls
  through caduceus to a configurable upstream (default: host `llama-swap`, model
  `llamacpp/gemma-4-12b`),
- lets you chat (streaming, session-persistent) with and configure each agent through a
  common transport,
- serves a simple **Web UI** (dashboard + add agent + streaming chat with thinking and
  tool-call display) on the loopback Control API.

> Status: under active construction via the AI-DLC workflow (see `aidlc-docs/`).
> Implemented: **U1 AI-Gateway · U2 Registry/Provisioner · U3 Transport/Chat ·
> U4 CLI/Daemon/Config · U5 Web UI**.

## Web UI

Start the daemon, then open the UI in a browser:

```bash
caduceus gateway start          # serves the Control API on 127.0.0.1:9700
# open http://127.0.0.1:9700/   (redirects to the Web UI at /ui/)
```

The UI lets you watch agents and their provisioning/health status (auto-refreshing),
create a local sandbox agent (with live provisioning progress) or register a remote one,
and chat with an agent — streaming responses with collapsible **thinking** blocks and
**tool-call** cards. It is served loopback-only with no authentication (personal local
tool). Chat history is best-effort loaded from a local agent's hermes session.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # unit + property-based (Hypothesis) tests
```

## Architecture (high level)

```
caduceus CLI ──HTTP(loopback)──> caduceus daemon ──┬─ AI-Gateway (OpenAI /v1)  ──> llama-swap
                                                    ├─ agent chat/control hub  ──> hermes agents
                                                    └─ agent registry + state
```

See `aidlc-docs/inception/` (requirements, design) and `aidlc-docs/construction/` (per-unit design + code).
