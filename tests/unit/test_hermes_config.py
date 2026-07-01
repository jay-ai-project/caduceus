"""Unit tests for the PURE hermes config renderer (caduceus/agents/hermes_config.py).

Focus: the rendered config.yaml must run the agent **unattended** — hermes' default
`approvals.mode=manual` would block dangerous commands on an approval prompt that
caduceus never answers, hanging the turn (BR-Q8).
"""

from __future__ import annotations

import yaml

from caduceus.agents.hermes_config import (
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


def test_remote_guidance_tells_operator_to_disable_approvals():
    text = remote_setup_guidance("http://gw/v1", "tok", "default")
    assert "approvals.mode: off" in text
