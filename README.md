# Caduceus

A local-first **gateway hub + CLI** for orchestrating sandboxed [hermes](https://) agents.

Caduceus:
- provisions isolated hermes agents in `sbx` Docker sandboxes (or registers remote ones),
- acts as a central **AI-Gateway** (OpenAI-compatible) so agents route their LLM calls
  through caduceus to a configurable upstream (default: host `llama-swap`, model
  `llamacpp/gemma-4-12b`),
- lets you chat (streaming, session-persistent) with and configure each agent through a
  common transport.

> Status: under active construction via the AI-DLC workflow (see `aidlc-docs/`).
> Implemented so far: **U1 — AI-Gateway** (OpenAI-compatible LLM proxy).

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
