# U6 — Build & Test Summary (`caduceus gateway config`)

Reuses the project-wide build/unit-test instructions (`build-instructions.md`,
`unit-test-instructions.md`); this file records U6-specific results and the live
integration procedure for the new command.

## Build Status
- **Tool**: hatchling (PEP 517) via `python -m build`; editable install via `pip install -e .`.
- **Editable install**: ✅ `caduceus --help` works (console script intact).
- **Import**: ✅ `caduceus.config.gateway_config` imports (`GatewayConfigService`, validators, store).
- **Wheel**: ✅ `caduceus-0.1.0-py3-none-any.whl` builds. No new runtime dependency (stdlib `tomllib`/`urllib`).

## Unit + Property Tests
- **Command**: `.venv/bin/python -m pytest`
- **Result**: ✅ **208 passed** (was 174 before U6; **+34**).
- New coverage:
  - `test_gateway_config.py` — URL/model validation, atomic key-preserving `config.toml` write
    (incl. nested `[timeouts]` preservation, no temp leftover), DTO round-trip, service persist+hot-apply,
    invalid-input-writes-nothing, env-override detection.
  - `test_cli_gateway_config.py` — view/set daemon-up (fake client) + offline (tmp HOME), exit 0/2, env-shadow warning.
  - `test_control_api_gateway_config.py` — `GET`/`POST /gateway/config`, 200 apply+persist+hot-apply, 400 validation/empty.
  - `test_gateway_config_pbt.py` — PBT-GC1 (validation totality/idempotence), PBT-GC2 (round-trip preserves
    unrelated keys), PBT-GC3 (apply idempotence).

## Integration — real `caduceus` entry point

### Scenario 1 — Offline (daemon down): file-edit path ✅
Temp `HOME`, no `CADUCEUS_*` env, daemon not running:
- `gateway config` (empty) → all "(not set)", `source: file`.
- `gateway config --upstream-url http://localhost:11434/v1 --model llama3` → "persisted … effective on next start";
  `config.toml` written with both keys.
- `gateway config --get` → reflects new values; `--json` well-formed.
- `gateway config --upstream-url notaurl` → validation message, **exit 2**, nothing written.
- env-shadow: with `CADUCEUS_DEFAULT_MODEL` set, set still persists **and** prints the shadow warning (BR-GC7).

### Scenario 2 — Live (daemon running): hot-apply, no restart ✅
Temp `HOME`, `config.toml` pre-seeded (`model-A`), `caduceus gateway start` backgrounded, `/healthz` up:
- `gateway config` → `source: live`, shows `model-A`.
- `gateway config --model model-B` → "applied live (no restart)".
- **Fresh** `gateway config --get` (new HTTP request to the still-running daemon) → `model-B`
  ⇒ the running daemon's in-memory `Settings` was mutated (BR-GC5) — **no restart**.
- `config.toml` persisted to `model-B`. Daemon shut down cleanly (SIGTERM).

### Live procedure (reproduce)
```bash
export HOME=$(mktemp -d); mkdir -p "$HOME/.caduceus"
printf 'upstream_base_url = "http://localhost:11434/v1"\ndefault_model = "model-A"\n' > "$HOME/.caduceus/config.toml"
caduceus gateway start &            # control API on 127.0.0.1:9700 (no Docker needed for config)
caduceus gateway config             # source: live
caduceus gateway config --model model-B   # applied live (no restart)
caduceus gateway config --get       # shows model-B
caduceus gateway stop
```
> Note: the config routes are loopback-only on the Control API and require no Docker/sbx/agents.

## Performance
- N/A as a gate (personal local tool; the command is a single config read/write + in-memory mutation).

## Overall
- **Build**: ✅ Success · **All tests**: ✅ 208/208 · **Live (offline + hot-apply)**: ✅ verified.
- **Ready for Operations**: Yes (Operations is a placeholder).
