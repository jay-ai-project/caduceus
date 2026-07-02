"""PURE rendering of an agent's hermes config pointing the LLM provider at the
caduceus AI-Gateway (BR-A5).

NOTE the rendered text **contains the agent's bearer token** (`api_key` inline):
hermes refuses to forward OPENAI_API_KEY to a non-openai.com base_url (#28660),
so an inline key is required. The file only ever lives inside the agent's
container (injected via `docker cp`, chowned/chmod 640 by the image's init) —
it is never written to the host.
"""

from __future__ import annotations

#: Toolsets we render explicitly into `platform_toolsets.api_server`.
#:
#: caduceus drives every agent over the hermes **api_server** platform. When
#: `platform_toolsets.api_server` is ABSENT, hermes falls back to a subset-inference
#: path (does the configurable toolset's tools ⊆ the `hermes-api-server` composite?)
#: to decide which toolsets are on. That path silently drops `terminal`: the desktop-only
#: `read_terminal` tool registers itself into the `terminal` toolset once the full tool
#: registry loads, so `resolve_toolset("terminal") == {terminal, process, read_terminal}`,
#: and `read_terminal` is NOT in the `hermes-api-server` composite → the subset check fails
#: → `terminal` (and `process`) never reach the model. The agent then has only `execute_code`
#: and loops forever trying to call a non-existent `terminal()` from inside the sandbox.
#:
#: Rendering this list explicitly forces hermes' "explicit config" branch (direct membership,
#: no subset inference), so `terminal` survives. The list mirrors the `hermes-api-server`
#: default's *intent* (its composite mapped back to configurable toolset keys) PLUS `terminal`
#: — i.e. exactly what a native `hermes gateway run` would expose if not for the read_terminal
#: bug. Interactive-only toolsets (clarify, tts, computer_use) and default-off ones
#: (homeassistant, spotify, moa, video, x_search) are intentionally excluded, matching the
#: api_server platform's non-interactive default.
#:
#: `web` is listed for forward-compat: `web_search`/`web_extract` are check_fn-gated on a
#: configured search backend (exa/tavily/firecrawl/ddgs/…), which caduceus does not yet
#: provision — so today those tools are simply filtered out and never reach the model
#: (removing the toolset key changes nothing the model sees). Keeping the key here means the
#: moment a backend IS configured, the tools light up with no code change. Until then the
#: `tool_loop_guardrails.hard_stop` set below bounds any hallucinated web_search() retries.
API_SERVER_TOOLSETS = (
    "browser",
    "code_execution",
    "cronjob",
    "delegation",
    "file",
    "image_gen",
    "memory",
    "session_search",
    "skills",
    "terminal",
    "todo",
    "vision",
    "web",
)


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


def render_hermes_config(aigateway_url: str, model_alias: str = "default",
                         api_key: str | None = None, workspace: str | None = None) -> str:
    """Render the hermes config.yaml text routing the LLM through caduceus.

    Matches the verified hermes 0.17.0 `model:` schema (Build & Test 2026-06-30):
    a custom provider with base_url + default model alias.

    The bearer token is written inline as `api_key` (and `key_env` is set as a
    backup). hermes refuses to forward `OPENAI_API_KEY` to a non-openai.com
    base_url (#28660), and its streaming-completion client does not pick up
    `key_env` for every path — so an inline `api_key` is required for the agent
    to authenticate to the caduceus AI-Gateway. The file lives only inside the
    agent's isolated sandbox (written 600).

    `approvals.mode: off` runs the agent unattended: caduceus drives hermes over
    the API server with no human in the approval loop, so hermes' default
    `manual` mode would BLOCK dangerous commands / execute_code on an
    `approval.request` event forever (the run hangs `waiting_for_approval` and
    the model retries indefinitely). `off` bypasses every approval prompt; the
    unconditional hardline blocklist + sudo-stdin guard remain as safety floors
    that `off` cannot lift. (hermes normalizes both the string `"off"` and the
    YAML-bool `off`; we quote it to keep intent explicit.)
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
    # Unattended operation (BR-Q8): no human is present to answer approvals.
    lines.append("approvals:")
    lines.append('  mode: "off"')
    # Pin the api_server toolset surface explicitly so `terminal` reaches the model.
    # Without this, hermes' subset-inference for an unspecified api_server platform drops
    # `terminal` (read_terminal pollutes the `terminal` toolset; see API_SERVER_TOOLSETS).
    lines.append("platform_toolsets:")
    lines.append("  api_server:")
    for toolset in API_SERVER_TOOLSETS:
        lines.append(f"  - {toolset}")
    # Bound the tool loop: hermes ships with hard_stop DISABLED, so when the model wants a
    # capability it lacks (e.g. web_search with no search backend) it can retry a failing /
    # hallucinated tool call forever. Enabling hard_stop makes hermes abort the turn after a
    # run of repeated failures / no-progress calls (default thresholds kept). Defence in depth
    # against runaway turns for ANY missing-or-failing tool, not just web. (BR-Q8)
    lines.append("tool_loop_guardrails:")
    lines.append("  hard_stop_enabled: true")
    if workspace:
        # Point the agent's gateway cwd at its persistent (bind-mounted) workspace so
        # artifacts land there, not in the ephemeral HERMES_HOME. Set via config (not the
        # deprecated TERMINAL_CWD env). The workspace is nested under HERMES_HOME so the
        # image-default HERMES_WRITE_SAFE_ROOT=/opt/data still permits writes to it.
        lines.append("terminal:")
        lines.append(f"  cwd: {workspace}")
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


def dashboard_env(username: str, password: str) -> dict[str, str]:
    """Env that enables the image's s6-supervised `hermes dashboard` service (U11).

    The dashboard binds 0.0.0.0 inside the container (host-exposed on loopback only),
    which engages hermes' auth gate — satisfied by the bundled basic password provider
    (BR-DB1/DB2). Username = agent name, password = caduceus-minted secret.
    """
    return {
        "HERMES_DASHBOARD": "true",
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": username,
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": password,
    }


def remote_setup_guidance(aigateway_url: str, token: str, model_alias: str = "default",
                          own_auth: bool = False) -> str:
    """Instructions returned on `register` so the user can route a remote hermes
    through caduceus (Q7; caduceus cannot auto-configure remote).

    `own_auth=True` (`register --auth <key>`): caduceus authenticates to the remote
    with the key the user supplied, so its existing API_SERVER_KEY stays untouched.
    Otherwise the caduceus-minted token doubles as the remote's API-server key.
    """
    step1 = (
        "  1. Its API server (hermes gateway run) keeps its existing bearer key —\n"
        "     caduceus talks to it over HTTP/SSE with the --auth key you provided."
        if own_auth else
        "  1. Enable its API server (hermes gateway run) with a bearer key and reachable URL;\n"
        "     caduceus talks to it over HTTP/SSE at that URL with the token below\n"
        "     (set API_SERVER_KEY to that token)."
    )
    return (
        "To register this remote hermes with caduceus:\n"
        f"{step1}\n"
        "  2. Route its LLM provider through the caduceus AI-Gateway:\n"
        f"       base_url = {aigateway_url}\n"
        f"       api_key (OPENAI_API_KEY) = {token}\n"
        f"       model = {model_alias}\n"
        "  3. Set `approvals.mode: off` in its config.yaml so it runs unattended;\n"
        "     otherwise hermes blocks dangerous commands waiting for an in-chat approval\n"
        "     that caduceus never sends, and the turn hangs."
    )
