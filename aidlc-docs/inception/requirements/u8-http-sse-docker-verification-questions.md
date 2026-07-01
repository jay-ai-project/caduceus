# U8 — HTTP/SSE Transport + Docker Runtime Migration — Verification Questions

This is a **re-architecture** cycle. Goal (as I understand it):

1. Replace the current **`hermes acp` (stdio over `sbx exec`)** local transport with the
   official **hermes API Server** (HTTP + SSE) — chat, streaming, stop, approval, session
   history, health.
2. Migrate local-agent communication to **HTTP/SSE**, and thereby **unify** the Local vs
   Remote transport branch into a single HTTP/SSE transport.
3. Replace **`sbx` (Docker Sandboxes)** with **plain Docker containers**, because `sbx`
   does not accept inbound requests (an HTTP server needs inbound).
4. Add **gVisor (`runsc`) as an optional container runtime** — not a hard dependency:
   default `runc`; opt into `runsc` via config when the user has installed gVisor.

> **Terminology note:** hermes calls its API server a "gateway"; caduceus already has its
> own `caduceus gateway` (the daemon = AI-Gateway + Control API + Web UI). To avoid
> collision, in caduceus docs/code I'll call hermes's server the **"hermes API server"**
> and keep **"gateway"** meaning the caduceus daemon. Please flag if you'd prefer otherwise.

Please answer each question after its `[Answer]:` tag (letter choice; use **Other** to write your own).

---

## Question 1 — Which hermes API surface do we standardize the transport on?
The hermes API server exposes several families. We need chat + SSE streaming + **stop** +
**approval** + **session history messages** + **health**. Which surface should the unified
transport target?

A) **Sessions + Runs (composed)** *(recommended)* — persistent per-agent session via
   `POST /api/sessions` + `POST /api/sessions/{id}/chat/stream` (SSE) + history via
   `GET /api/sessions/{id}/messages`; use the Runs API (`/v1/runs/{id}/stop`,
   `/v1/runs/{id}/approval`, `/v1/runs/{id}/events`) for stop/approval/events. Best match
   to today's "one persistent session per agent (auto-resume)" model plus native history.

B) **Runs API only** — `POST /v1/runs` + `GET /v1/runs/{id}/events` (SSE) + stop + approval;
   reconstruct history from run events. Simpler surface, but history/session-continuity is
   more manual.

C) **OpenAI-compatible `/v1/chat/completions`** (with `hermes.tool.progress` events) for
   chat/stream only; **no** stop/approval/history in v1 (defer those).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 2 — How does caduceus reach each agent container's hermes API server (inbound)?
Plain Docker containers accept inbound, unlike `sbx`. We must pick how the daemon connects
to a container's hermes API server (listening on `:8642` inside the container).

A) **Publish to host loopback** *(recommended)* — `docker run -p 127.0.0.1:<hostPort>:8642`;
   caduceus connects to `http://127.0.0.1:<hostPort>`. Simple, works on WSL2, loopback-only
   (not exposed off-host). caduceus allocates/records the host port per agent.

B) **Bridge container IP** — no host port publish; caduceus resolves the container's IP on
   the Docker bridge and connects to `http://<containerIP>:8642`. No host ports consumed,
   but relies on host→container bridge routing.

C) **Dedicated user network + DNS** — put agent containers on a named Docker network and
   connect by container name; requires the daemon to also be able to resolve that network.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3 — Where should the gVisor setup/guidance live?
You want an optional setup step that detects gVisor and guides installation if missing.

A) **New `caduceus doctor` / `caduceus setup` command** *(recommended)* — checks Docker,
   the hermes image, and whether `runsc` is available; prints install guidance for gVisor
   when missing (does not auto-install). Run on demand.

B) **Fold into `caduceus gateway` startup bootstrap** — the existing interactive bootstrap
   also checks/guides gVisor when relevant.

C) **Documentation only** — README explains how to install gVisor and enable it; no
   interactive check command.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 4 — Behavior when `runsc` is configured but not available on the host?
If config requests `runsc` but the runtime isn't installed/registered with Docker:

A) **Fail fast with guidance** *(recommended)* — refuse to spawn the container and tell the
   user how to install gVisor (or switch back to `runc`). No silent security downgrade —
   if the user asked for the stronger runtime, we don't quietly weaken it.

B) **Warn and fall back to `runc`** — log a clear warning and spawn with `runc` so the agent
   still works.

C) **Auto-detect only** — no explicit setting; use `runsc` automatically when present, else
   `runc` (no failure, no config key).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5 — How does the user select the container runtime?
(Assuming a `runc`-default with opt-in `runsc`.)

A) **Extend `caduceus gateway config`** *(recommended)* — add `--runtime runc|runsc`
   (shown in `--get`/`--json`), persisted to `config.toml`, applied to newly-spawned
   containers. Consistent with the U6 config command. Existing containers keep their runtime
   until recreated.

B) **Config file / env only** — `container_runtime` in `config.toml` (and a
   `CADUCEUS_CONTAINER_RUNTIME` env var); no dedicated CLI subcommand.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 6 — What happens to agents created under the old `sbx` architecture?
Existing agents were provisioned as `sbx` sandboxes and driven over ACP.

A) **No migration (clean cut)** *(recommended)* — this is a personal local tool and a full
   re-architecture; on upgrade, old sbx-backed agent records are treated as stale. `agent ls`
   marks them unusable and the user recreates them as Docker-container agents. Simplest,
   least code.

B) **One-time migration** — a command that recreates each existing agent as a Docker
   container (best-effort; workspace preserved where possible).

C) **Keep both runtimes** — support sbx-backed and docker-backed agents side by side.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 7 — Remote agents and the unified transport
Today: remote = a registered hermes endpoint (URL), read-only lifecycle; local = sbx-managed.

A) **Unify transport, keep remote as a management distinction** *(recommended)* — one
   HTTP/SSE hermes-API-server client for **both**; drop `AcpTransport` and `ServeTransport`.
   "Local" = caduceus spawns/manages the Docker container; "remote" = user-registered hermes
   **API server** URL + bearer, lifecycle read-only. `register` guidance updates to point at
   the API-server URL.

B) **Unify transport and drop the remote-agent feature** — local Docker agents only; remove
   `register`/remote code paths entirely.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 8 — Tool approval handling (hermes exposes an approval endpoint)
hermes can gate tool calls behind approval. What behavior do we want in v1?

A) **Auto-approve, surface for visibility** *(recommended)* — agents run autonomously
   (current behavior); tool-call events are shown in the stream/Web UI, but caduceus does not
   block waiting for user approval. Keep the approval endpoint wired but unused/auto.

B) **Interactive approval** — chat/Web UI prompts the user to approve/deny each tool call
   before it runs (uses `/v1/runs/{id}/approval`).

C) **Disable approval entirely** — configure hermes so no approval gating occurs.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 9 — Extensions for this cycle
Prior cycles (U1–U7) ran with: **Security Baseline = No**, **Resiliency Baseline = Yes (full)**,
**Property-Based Testing = Yes (full)**. Given this cycle touches the container runtime, the
network trust boundary (inbound HTTP to agents), and bearer-token handling:

A) **Inherit as-is** — Security=No, Resiliency=Yes, PBT=Yes.

B) **Also enable Security Baseline** for this cycle (new inbound network surface + optional
   sandbox-escape hardening via runsc make a security pass worthwhile).

X) Other (please describe after [Answer]: tag below)

[Answer]: According to your suggestion (best effort)

---

*When you've filled in the answers, tell me you're done and I'll analyze them (and raise any
follow-ups) before writing the requirements document.*
