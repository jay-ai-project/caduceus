# Caduceus hermes agent image — SLIM (Infra Design Q1=A).
#
# Pinned to hermes-agent v0.17.0 (parity with the host). Excludes the heavy
# browser (Playwright), Node, and ffmpeg toolchains; keeps serve + LLM +
# file/shell tooling. The exact install line (pip vs uv; extras) and the
# in-sandbox config path are VALIDATED IN BUILD & TEST (U2 Infra Design §8).
#
# Build:  docker build -t caduceus/hermes:0.17.0 --build-arg HERMES_VERSION=0.17.0 images/hermes
FROM python:3.12-slim-bookworm

ARG HERMES_VERSION=0.17.0
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Minimal runtime + build deps (no node / playwright / ffmpeg).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep procps \
        gcc g++ make libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install hermes-agent at the pinned tag. (Validated in Build & Test — the repo
# uses uv; if a plain pip install needs extras or a uv bootstrap, adjust here.)
RUN pip install "git+https://github.com/NousResearch/hermes-agent.git@v${HERMES_VERSION}"

# Caduceus places a per-agent config at $HERMES_HOME/config.yaml (provider ->
# AI-Gateway) and sets OPENAI_API_KEY at provision time.
ENV HERMES_HOME=/root/.hermes
RUN mkdir -p /root/.hermes

# `hermes serve` is started by caduceus at provision time (not baked as CMD),
# so the same image also supports `sbx exec` for config edits and logs.
CMD ["sleep", "infinity"]
