# U2 Registry & Provisioner — Infrastructure Design Plan

**Unit**: U2. **Stage**: Infrastructure Design (the project's highest-risk integration).

This plan (A) lists U2 infra artifacts and (B) asks **one** genuine user-facing question (hermes image scope). The rest is decided from spikes and documented.

## Spike-grounded facts
- **hermes-agent v0.17.0** (NousResearch) — git project, ships an official multi-stage `Dockerfile` (debian13 + uv-python + node22 + s6-overlay; Playwright/browser optional). `name = hermes-agent`, `requires-python >=3.11,<3.14`.
- **custom_providers** = list of `{name, base_url, model, api_mode}`; bearer to an OpenAI-compatible base_url is the OpenAI-SDK key (set via `OPENAI_API_KEY` / credential pool keyed by base_url).
- **Networking** (earlier spike): containers reach the host AI-Gateway at the docker **bridge IP `172.17.0.1`** unconditionally (no `--add-host` needed).

## Decisions (documented; not asking)
- **Image source**: build `images/hermes/Dockerfile`, **pinned to hermes-agent v0.17.0** (parity with the user's host hermes; overridable). Reuse/trim the upstream Dockerfile.
- **Agent → AI-Gateway**: provider `base_url = http://172.17.0.1:9701/v1`, `model = default` (sentinel), bearer = agent token via `OPENAI_API_KEY=<token>` in the sandbox env (validated in Build & Test; fallback = hermes credential-pool var).
- **Provisioning sequence**: `sbx create shell -t caduceus/hermes:0.17.0 --name cad-<name>` → render+`sbx cp` hermes config (model→AI-Gateway) + set env → `hermes serve --host 0.0.0.0` (caduceus-generated serve credential) via `sbx exec -d` → `sbx ports --publish` the serve port to host loopback (= transport endpoint) → health check.
- **caduceus → agent** (transport, U3 uses): `http://127.0.0.1:<published-port>` + serve credential.
- **Validation items → Build & Test**: exact OpenAI key env var vs credential pool; `hermes serve` bind/auth flags; in-sandbox hermes config path; image trim correctness.

## Part A — Artifacts to generate (after the question)
- [x] `construction/u2-registry-provisioner/infrastructure-design/infrastructure-design.md` — image strategy, provisioning sequence, config/auth mechanism, networking, paths, security, validation items
- [x] `construction/u2-registry-provisioner/infrastructure-design/deployment-architecture.md` — per-agent runtime diagram (sandbox internals, ports, flows)

---

## Part B — Question

## Question 1 — hermes 에이전트 이미지 범위 (slim vs full)
각 에이전트 샌드박스에 들어갈 hermes 이미지를 어디까지 포함할까요? (빌드시간/이미지크기 ↔ 에이전트 기능 트레이드오프)

A) **슬림-실용 (권장)** — python + hermes-agent + `serve`/LLM/파일·셸 도구 + ripgrep + git. **브라우저(Playwright)·node·ffmpeg 제외**. 빌드 빠르고 가벼움. 웹브라우징/이미지/음성 등 무거운 툴은 비활성.

B) **풀(full)** — 업스트림 Dockerfile 그대로(node22 + Playwright 브라우저 + ffmpeg 포함). 모든 hermes 툴 사용 가능하나 이미지 크고 빌드 느림.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
