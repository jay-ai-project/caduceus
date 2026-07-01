# Caduceus hermes agent image — runs the hermes API server (U8).
#
# Pinned to hermes-agent v0.17.0 (parity with the host). Excludes the heavy browser
# (Playwright), Node, and ffmpeg toolchains. The container runs `hermes gateway run`
# with the API-server platform enabled (via API_SERVER_* env passed at `docker run`),
# so caduceus drives chat over HTTP/SSE at :8642 — no ACP/stdio, no web dashboard.
# `aiohttp` is installed explicitly because the API-server platform requires it.
#
# Build:  docker build -t caduceus/hermes:0.17.0 --build-arg HERMES_VERSION=0.17.0 images/hermes
FROM python:3.12-slim-bookworm

# HERMES_VERSION is the human/marketing version (used only for the image tag).
# HERMES_GIT_REF is the actual git ref to install — hermes-agent tags are
# date-based (e.g. v2026.6.19 == release 0.17.0), so the two differ.
ARG HERMES_VERSION=0.17.0
ARG HERMES_GIT_REF=v2026.6.19
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_HOME=/root/.hermes \
    HERMES_ACCEPT_HOOKS=1

# Minimal runtime + build deps (no node / playwright / ffmpeg).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep procps \
        gcc g++ make libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent at the pinned git ref + aiohttp (required by the API-server
# platform). The `hermes gateway run` command ships with the base package.
RUN pip install "hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@${HERMES_GIT_REF}" aiohttp

# Caduceus copies a per-agent config to $HERMES_HOME/config.yaml (LLM provider ->
# AI-Gateway) before starting the container, and passes API_SERVER_* + OPENAI_API_KEY
# via `docker run -e`.
RUN mkdir -p /root/.hermes

# Run the hermes API server in the foreground (recommended for Docker). The
# API-server platform is enabled by API_SERVER_ENABLED/API_SERVER_KEY (docker run -e),
# listening on API_SERVER_HOST:API_SERVER_PORT (0.0.0.0:8642), reachable from the host
# on a published loopback port.
CMD ["hermes", "gateway", "run"]
