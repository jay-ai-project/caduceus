# U7 — Build & Test Summary (Performance & Stability)

## Build
- ✅ Editable install imports clean (`caduceus`, agents.service, daemon.gateway, transport.chat).
- ✅ No new runtime dependency.

## Automated tests
- ✅ **225 unit + PBT pass** (was 208; +17) — incl. new `tests/pbt/test_u7_properties.py`
  (PBT-P1 reconcile totality, PBT-P2 async state machine, PBT-P3 single-`sbx ls` invariant,
  PBT-P4 shutdown safety).
- ✅ **3 e2e (Playwright web-UI) pass** — no regression from the create/list/shutdown changes.
- Total: **228 pass**.

## Live integration (Docker 29.4.0 + sbx + hermes 0.17.0 image + Ollama `ornith:9b`)
Real `caduceus` entry point, daemon detached. Each FR verified:

| Scenario | Result |
|---|---|
| **FR-U7-1** `agent ls` speed | 1 agent **4.26s**, 2 agents **3.77s** — flat in N (one `sbx ls`), was ~2×N. Empty `agent ls` **4.10s → 1.22s** (no `sbx ls` when no local agents). |
| **FR-U7-2** background create | `agent create` returned in **1.31s** (was blocking minutes); `agent ls` immediately showed `creating`. |
| async progression | `creating → running/healthy` visible in `agent ls` within ~6s, no client blocking. |
| **FR-U7-3/4** warm first chat | first chat right after `healthy` streamed `PONG` with no cold-start stall; reconnected-agent chat streamed `OK`. |
| **FR-U7-5** decouple + reconnect | `gateway stop` left both sandboxes **running**; `gateway start` reconciled from `sbx ls` → both `running/healthy`, immediately chat-able. |
| **FR-U7-6** correct status / resilience | `creating`/`running` reported accurately; a live `sbx ls` timeout during a concurrent create no longer errors `agent ls` (returns `ok=False`, keeps last-known lifecycle). |

## Defect found & fixed during live testing
- **U7-L1**: `list_statuses()` let a `sbx ls` **timeout** exception propagate (a concurrent
  `sbx create` starved `sbx ls` > 15s), so `agent ls` printed `sbx ls timed out` instead of
  degrading gracefully. Fixed: `list_statuses` now catches any error → `SandboxSnapshot(ok=False)`
  (BR-P2). Also added: skip the `sbx ls` entirely when there are no local agents (empty/all-remote
  `agent ls` is instant). PBT-P3 updated accordingly. All 225 still pass.

## Performance
- N/A as a gate (personal local tool), but the headline wins are real and measured above:
  `agent ls` is now O(1) in `sbx` calls; `create` is non-blocking; first chat is warm; gateway
  restart no longer disrupts running agents.

## Notes
- Deep health (`--deep`) and remote-agent probing paths unchanged.
- No LLM spend on health, warm-up, reconcile, or supervision (verified: warm-up stops at
  `session/new`).
