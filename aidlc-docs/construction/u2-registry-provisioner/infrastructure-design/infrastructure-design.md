# U2 Registry & Provisioner — Infrastructure Design

Maps U2 logical components to the local runtime + the hermes agent image. See [shared-infrastructure.md](../../shared-infrastructure.md). **Image scope = slim (Q1=A).**

## 1. hermes agent image (`images/hermes/Dockerfile`)
- **Pinned**: hermes-agent **v0.17.0** (parity with host; overridable via build arg).
- **Slim build** (Q1=A): `FROM python:3.12-slim-bookworm`; apt `ca-certificates curl git ripgrep libffi7 procps`; install hermes-agent at the pinned ref into a venv (e.g. `pip install "git+https://github.com/NousResearch/hermes-agent.git@v0.17.0"` — exact line validated in Build & Test, hermes uses `uv`); run non-browser `hermes postinstall` bits only. **Exclude** node/Playwright/ffmpeg.
- **Tag**: `caduceus/hermes:0.17.0`. Built idempotently by `ImageBuilder.ensure_image` (skip if present).
- **HERMES_HOME**: a known path in the image (e.g. `/root/.hermes`) so caduceus can place config deterministically.

## 2. Provisioning sequence (SbxProvisioner)
```
1. sbx create shell -t caduceus/hermes:0.17.0 --name cad-<name>
2. render hermes config (model -> AI-Gateway) and sbx cp into <HERMES_HOME>/config.yaml
   set env OPENAI_API_KEY=<agent-token>   (custom-provider bearer to AI-Gateway)
3. sbx exec -d cad-<name>  hermes serve --host 0.0.0.0 --port 9119   (+ serve credential)
4. sbx ports cad-<name> --publish 9119      -> host loopback port P  (transport endpoint)
5. HealthChecker.check(shallow): port P reachable + sandbox running
```
Failure after step 1 → compensate: `sbx rm cad-<name>`, discard token (BR-A7).

## 3. Agent hermes config (rendered per agent)
Logical config written into the sandbox:
```yaml
model:
  provider: custom
  default: default            # caduceus sentinel; AI-Gateway substitutes the real model
  base_url: http://172.17.0.1:9701/v1
  api_mode: chat_completions
custom_providers:
  - name: caduceus
    base_url: http://172.17.0.1:9701/v1
    model: default
    api_mode: chat_completions
```
Plus env `OPENAI_API_KEY=<agent-token>` so hermes sends `Authorization: Bearer <token>` to the AI-Gateway (BR-A5). *(Exact key var vs hermes credential-pool keyed by base_url is validated in Build & Test; OPENAI_API_KEY is the primary, the credential-pool var the fallback.)*

## 4. hermes serve (transport endpoint; used by U3)
- Started bound `0.0.0.0:9119` inside the sandbox (required for `sbx ports` publishing), so serve demands an auth provider → caduceus generates a **serve credential** and stores it on the record (`AgentRecord.serve_auth`).
- Published to host **loopback** via `sbx ports` → endpoint `http://127.0.0.1:<P>`. caduceus (U3) authenticates with `serve_auth`.

## 5. Networking summary
| Hop | Address |
|---|---|
| agent hermes → AI-Gateway | `http://172.17.0.1:9701/v1` (bridge IP; bearer=token) |
| AI-Gateway → upstream LLM | `http://localhost:9292/v1` (host; user-configured) |
| caduceus (U3) → agent serve | `http://127.0.0.1:<published>` (+ serve_auth) |

## 6. Storage / paths (host)
- `~/.caduceus/state.json` (registry; perms 600), `~/.caduceus/` (700). Tokens + serve creds inline in state (600).
- Image build context: `images/hermes/`.

## 7. Security posture (baseline; Security ext OFF)
- Token/serve-cred passed via env/config (not argv) → kept out of `ps`.
- AI-Gateway bound to bridge IP (containers+host only); serve published to loopback only.
- Secrets at rest 600; redacted in logs.

## 8. Validation items → Build & Test (real image/agent)
1. Exact hermes install line (pip vs uv; extras) in the slim Dockerfile.
2. Confirm hermes forwards `OPENAI_API_KEY` as the AI-Gateway bearer (else use credential-pool var).
3. `hermes serve` host/port/auth flags + the serve credential mechanism.
4. In-sandbox hermes config path / HERMES_HOME.
5. `sbx ports` publish + reachability of the published serve port from the host.
