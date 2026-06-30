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


def render_hermes_config(aigateway_url: str, model_alias: str = "default") -> str:
    """Render the hermes config.yaml text routing the LLM through caduceus."""
    return (
        "model:\n"
        "  provider: custom\n"
        f"  default: {model_alias}\n"
        f"  base_url: {aigateway_url}\n"
        "  api_mode: chat_completions\n"
        "custom_providers:\n"
        "  - name: caduceus\n"
        f"    base_url: {aigateway_url}\n"
        f"    model: {model_alias}\n"
        "    api_mode: chat_completions\n"
    )


def remote_setup_guidance(aigateway_url: str, token: str, model_alias: str = "default") -> str:
    """Instructions returned on `register` so the user can route a remote hermes
    through caduceus (Q2=A; caduceus cannot auto-configure remote in v1)."""
    return (
        "To route this remote hermes through caduceus, configure its LLM provider:\n"
        f"  base_url = {aigateway_url}\n"
        f"  api_key (OPENAI_API_KEY) = {token}\n"
        f"  model = {model_alias}"
    )
