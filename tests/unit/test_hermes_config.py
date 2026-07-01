"""Unit tests for the PURE hermes config renderer (caduceus/agents/hermes_config.py).

Focus: the rendered config.yaml must run the agent **unattended** — hermes' default
`approvals.mode=manual` would block dangerous commands on an approval prompt that
caduceus never answers, hanging the turn (BR-Q8).
"""

from __future__ import annotations

import yaml

from caduceus.agents.hermes_config import (
    API_SERVER_TOOLSETS,
    remote_setup_guidance,
    render_hermes_config,
)


def _parse(text: str) -> dict:
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def test_config_routes_model_through_aigateway():
    doc = _parse(render_hermes_config("http://127.0.0.1:9000/v1", "default", api_key="tok"))
    assert doc["model"]["base_url"] == "http://127.0.0.1:9000/v1"
    assert doc["model"]["default"] == "default"
    assert doc["model"]["provider"] == "custom"
    assert doc["model"]["api_key"] == "tok"
    assert doc["model"]["key_env"] == "OPENAI_API_KEY"


def test_config_disables_tool_approval_for_unattended_operation():
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    # Must be the string "off" (not the YAML boolean False) and never "manual".
    assert doc["approvals"]["mode"] == "off"
    assert isinstance(doc["approvals"]["mode"], str)


def test_approvals_off_present_even_without_api_key():
    doc = _parse(render_hermes_config("http://gw/v1", "default"))
    assert doc["approvals"]["mode"] == "off"
    assert "api_key" not in doc["model"]


def test_workspace_sets_terminal_cwd():
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok",
                                      workspace="/opt/data/workspace"))
    assert doc["terminal"]["cwd"] == "/opt/data/workspace"


def test_no_terminal_block_when_workspace_unset():
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    assert "terminal" not in doc


def test_api_server_toolsets_rendered_explicitly():
    """The config MUST pin `platform_toolsets.api_server` so hermes takes its
    explicit-config (direct-membership) branch instead of the subset-inference
    fallback that silently drops `terminal` for the api_server platform."""
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    rendered = doc["platform_toolsets"]["api_server"]
    assert rendered == sorted(API_SERVER_TOOLSETS)


def test_api_server_toolsets_include_terminal():
    """Regression: without an explicit list, hermes drops `terminal` (read_terminal
    pollutes the terminal toolset), leaving the agent with only execute_code and
    an infinite hallucinated-terminal() loop. `terminal` must always be present."""
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    rendered = doc["platform_toolsets"]["api_server"]
    assert "terminal" in rendered
    # These are the core capabilities an unattended caduceus agent relies on.
    for essential in ("terminal", "code_execution", "file"):
        assert essential in rendered


def test_api_server_toolsets_include_web_for_forward_compat():
    """`web` is listed even though its tools are check_fn-gated on a search backend caduceus
    doesn't yet provision (so they're filtered out today). Keeping the key means the tools
    light up automatically once a backend is configured — no code change needed. The loop a
    missing web_search() could cause is bounded by hard_stop, not by hiding the toolset."""
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    assert "web" in doc["platform_toolsets"]["api_server"]


def test_tool_loop_hard_stop_enabled():
    """hard_stop must be ON so a missing/failing tool aborts the turn instead of looping
    forever (hermes ships it disabled)."""
    doc = _parse(render_hermes_config("http://gw/v1", "default", api_key="tok"))
    assert doc["tool_loop_guardrails"]["hard_stop_enabled"] is True


def test_api_server_toolsets_present_even_without_workspace():
    doc = _parse(render_hermes_config("http://gw/v1", "default"))
    assert "terminal" in doc["platform_toolsets"]["api_server"]


def test_remote_guidance_tells_operator_to_disable_approvals():
    text = remote_setup_guidance("http://gw/v1", "tok", "default")
    assert "approvals.mode: off" in text
