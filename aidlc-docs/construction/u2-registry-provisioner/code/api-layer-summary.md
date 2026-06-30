# U2 — Adapters / Image Summary (code)

## Created (application code)
| File | Purpose |
|---|---|
| `caduceus/agents/provisioner.py` | `Provisioner` (Protocol) + `SbxProvisioner` — async `sbx` subprocess (argv form, timeouts); create/write_file(stdin)/start_serve(+publish)/stop/start/remove/status/logs (BR-A12) |
| `caduceus/agents/images.py` | `ImageBuilder.ensure_image` — idempotent `docker build` (skip if present) |
| `caduceus/agents/health.py` | `HealthChecker` + injectable `HealthProbes` (shallow/deep; **no LLM spend**; BR-A11/FR-L2) |
| `images/hermes/Dockerfile` | slim hermes-agent v0.17.0 image (no node/playwright/ffmpeg) |

## Test doubles
- `tests/fakes.py`: `FakeProvisioner` (records env/files/calls; `fail_on` to drive rollback), `FakeImageBuilder`, `FakeHealthChecker`. Real sbx/docker are NOT unit-tested — exercised in Build & Test.

## Verification
- **55/55 tests pass** (`pytest`) in venv (U1 31 + U2 24). Real Docker/sbx behind interfaces → fully mocked.

## Build & Test validation items (from U2 Infra Design §8)
1. exact hermes install line (pip vs uv/extras) in the slim Dockerfile;
2. `OPENAI_API_KEY` forwarded as the AI-Gateway bearer (else hermes credential-pool var);
3. `hermes serve` host/port/auth flags + serve credential;
4. in-sandbox hermes config path / HERMES_HOME;
5. `sbx ports` publish + reachability.

## Deferred to other units
- `HealthProbes` real wiring (sandbox_status from Provisioner, endpoint socket check, upstream check from U1, transport probe from U3) is assembled by U4.
- `Registry.token_lookup` is injected into the U1 AI-Gateway by U4.
