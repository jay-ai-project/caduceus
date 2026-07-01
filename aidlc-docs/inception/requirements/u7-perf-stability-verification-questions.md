# U7 — Performance & Stability — Requirements Verification Questions

This cycle addresses four concerns you raised about Caduceus performance & stability.
Please answer each question by filling the letter after `[Answer]:`. Every question has a
**Recommended** option (marked ✅) reflecting my diagnosis — you can just confirm those, or
pick another / write your own after `X) Other`.

---

## Diagnosis summary (what I found in the code, for context)

1. **`agent ls` is slow** — confirmed root cause. A single `sbx ls --json` call costs **~2.5–3.9s**
   on your machine, and `AgentService.list(probe=True)` runs it **twice per agent, sequentially**:
   once in `provisioner.status()` (lifecycle reconcile) and again inside `HealthChecker.check()`
   → `sandbox_status()` (shallow health). So N agents = **2×N** slow subprocess spawns, even though
   one `sbx ls` already returns *every* sandbox.

2. **Agent only "boots" on first chat** — confirmed. `agent create` creates the sandbox + writes
   config, but never starts `hermes acp`. The first chat's `AcpTransport.open()` pays the full
   cold start (spawn `sbx exec hermes acp` → `initialize` → `session/new` → hermes provider/model
   probing). That first-turn latency is the bad UX.

3. **`create` blocks synchronously** — the CLI streams provisioning progress and blocks (up to
   `PROVISION_TIMEOUT = 1800s`) until the agent is fully provisioned.

4. **Stability** — `agent ls` status can be mis-reported (a stopped-but-existing sandbox that
   `sbx ls` doesn't list as running currently maps to `missing` → `failed`); and daemon shutdown
   is entangled with agent perception. Sandboxes are persistent Docker containers and *should*
   survive a gateway restart.

---

## Question 1 — Async `create` (background provisioning)
You want `create` to return immediately and provision in the background so `agent ls` shows live
progress. How should the default behave?

A) ✅ `agent create` returns immediately; the agent appears as `creating` right away and a
   **background task** provisions it → `running` → warms it → `healthy`, updating `agent ls`
   live. Add an opt-in `--wait` flag for scripts that want to block until ready.

B) Keep `create` blocking by default (current behavior), but add an opt-in `--detach`/`--async`
   flag for background provisioning.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — "Chat-ready" warm-up depth
After provisioning, how far should the background task take the agent so that a `running`+`healthy`
agent can chat instantly?

A) ✅ **Full protocol warm-up (no LLM spend)**: spawn the pooled `hermes acp` process and run
   `initialize` + `session/new` so the first real chat skips all cold-start. Keeps the warmed
   transport pooled/reused for the first turn. No model tokens are spent.

B) **Sandbox-only**: just ensure the sandbox is running; do not pre-spawn `hermes acp` (first
   chat still pays the acp cold start, but `create` is simpler).

C) **Warm-up + a tiny model ping** to also prove the LLM path end-to-end (spends a few tokens
   per created agent).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — `agent ls` performance fix
How should `agent ls` be made fast while staying accurate?

A) ✅ **Single batched snapshot**: call `sbx ls --json` **once per `ls`**, build a name→status map,
   and reconcile lifecycle **and** shallow health for all agents from that one snapshot (no
   per-agent re-probe). Authoritative and fast (~one `sbx ls`, not 2×N).

B) **Registry-only instant listing** (like the Web UI's `probe=false` path): `agent ls` returns
   cached state instantly and relies on the background Supervisor sweep to keep it fresh; add
   `--probe` for an authoritative on-demand refresh.

C) Both: default to (A)'s single-snapshot probe, but also add a `--fast` flag for (B)'s instant
   cached listing.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — Gateway shutdown vs. agent (sandbox) lifecycle
You observed agents flipping to `stopped` when only the gateway was stopped, and want them to keep
running. What's the intended coupling?

A) ✅ **Fully decouple**: stopping the daemon (`gateway stop`) leaves all agent sandboxes running.
   Only explicit `agent stop` / `agent rm` stop or remove a sandbox. On `gateway start`, the daemon
   **reconciles from `sbx ls`** and marks still-running sandboxes as `running`/`healthy`, ready to
   chat immediately (pooled acp transports are re-warmed lazily or on boot).

B) Decouple as in (A), but also add an opt-in `gateway stop --stop-agents` for users who *do* want
   everything torn down together.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — Surfacing provisioning / failure state
With background provisioning, failures happen off the main thread. How should they surface?

A) ✅ On provisioning failure, set lifecycle=`failed` with a short error detail visible in
   `agent ls` (and its health `detail`); the compensating sandbox cleanup still runs. Recover by
   `agent rm` + recreate. A `creating` agent that's still in progress shows a `creating` status.

B) Same as (A), but also keep a small per-agent "last error" / progress log retrievable via
   `agent logs` or a new `agent status <name>` command.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

**Extensions** (inherited from prior cycles, not re-asked): Security Baseline = **No**,
Resiliency Baseline = **Yes (full)**, Property-Based Testing = **Yes (full)**. If you want to
change any of these for U7, note it here:

[Extensions override, if any]: according to your suggestion
