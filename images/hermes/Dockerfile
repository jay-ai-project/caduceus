# Caduceus hermes agent image — SLIM (Infra Design Q1=A).
#
# Pinned to hermes-agent v0.17.0 (parity with the host). Excludes the heavy
# browser (Playwright), Node, and ffmpeg toolchains. Installs the lightweight
# `[acp]` extra (agent-client-protocol) so the agent speaks ACP over stdio —
# caduceus drives chat via `hermes acp` (stdio JSON-RPC), NOT the web dashboard
# (`hermes serve`/`dashboard`), which requires a full Node web build.
# Build & Test (2026-06-30) confirmed: serve needs a Node-built web dist;
# ACP needs only the `[acp]` extra. See aidlc-docs build-and-test summary.
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
    PIP_NO_CACHE_DIR=1

# Minimal runtime + build deps (no node / playwright / ffmpeg).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep procps \
        gcc g++ make libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent (+ the lightweight ACP adapter) at the pinned git ref.
RUN pip install "hermes-agent[acp] @ git+https://github.com/NousResearch/hermes-agent.git@${HERMES_GIT_REF}"

# Caduceus places a per-agent config at $HERMES_HOME/config.yaml (provider ->
# AI-Gateway) and sets OPENAI_API_KEY at provision time.
ENV HERMES_HOME=/root/.hermes
RUN mkdir -p /root/.hermes

# The agent is driven via `hermes acp` (stdio), spawned per-connection by
# caduceus through `sbx exec -i`; the long-lived container just idles, and the
# same image also supports `sbx exec` for config edits and logs.
CMD ["sleep", "infinity"]
