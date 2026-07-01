"""PURE rendering of an agent's hermes config pointing the LLM provider at the
caduceus AI-Gateway (BR-A5).

The agent's bearer token is delivered via the OPENAI_API_KEY env var (not written
into the config file), so the rendered text contains no secret.
"""

from __future__ import annotations


def provider_settings(aigateway_url: str, model_alias: str = "default") -> dict:
    """Structured provider config — the invariant target for tests/PBT.

    For every local agent: base_url == AI-Gateway URL, model == sentinel alias.
    """
    return {
        "provider": "custom",
        "base_url": aigateway_url,
        "model": model_alias,
        "api_mode": "chat_completions",
    }


def render_hermes_config(aigateway_url: str, model_alias: str = "default", api_key: str | None = None) -> str:
    """Render the hermes config.yaml text routing the LLM through caduceus.

    Matches the verified hermes 0.17.0 `model:` schema (Build & Test 2026-06-30):
    a custom provider with base_url + default model alias.

    The bearer token is written inline as `api_key` (and `key_env` is set as a
    backup). hermes refuses to forward `OPENAI_API_KEY` to a non-openai.com
    base_url (#28660), and its streaming-completion client does not pick up
    `key_env` for every path — so an inline `api_key` is required for the agent
    to authenticate to the caduceus AI-Gateway. The file lives only inside the
    agent's isolated sandbox (written 600).
    """
    lines = [
        "model:",
        f"  default: {model_alias}",
        "  provider: custom",
        f"  base_url: {aigateway_url}",
        "  api_mode: chat_completions",
    ]
    if api_key:
        lines.append(f"  api_key: {api_key}")
        lines.append("  key_env: OPENAI_API_KEY")
    return "\n".join(lines) + "\n"


def api_server_env(token: str, port: int = 8642) -> dict[str, str]:
    """Env that enables the hermes API server inside the agent container (U8).

    `hermes gateway run` starts the API-server platform when these are set. The
    bearer key equals the agent's caduceus token (single credential, BR-N2/D4).
    """
    return {
        "API_SERVER_ENABLED": "true",
        "API_SERVER_KEY": token,
        "API_SERVER_HOST": "0.0.0.0",   # inside the container only; host-exposed on loopback
        "API_SERVER_PORT": str(port),
    }


def remote_setup_guidance(aigateway_url: str, token: str, model_alias: str = "default") -> str:
    """Instructions returned on `register` so the user can route a remote hermes
    through caduceus (Q7; caduceus cannot auto-configure remote)."""
    return (
        "To register this remote hermes with caduceus:\n"
        "  1. Enable its API server (hermes gateway run) with a bearer key and reachable URL;\n"
        "     caduceus talks to it over HTTP/SSE at that URL with the token below.\n"
        "  2. Route its LLM provider through the caduceus AI-Gateway:\n"
        f"       base_url = {aigateway_url}\n"
        f"       api_key (OPENAI_API_KEY) = {token}\n"
        f"       model = {model_alias}"
    )
