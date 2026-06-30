# U1 AI-Gateway — Business Logic Summary (code)

## Created (application code at workspace root)
| File | Purpose |
|---|---|
| `caduceus/common/errors.py` | `ProxyError` + OpenAI error shaping (`to_openai`), helpers (auth/invalid/upstream/timeout) |
| `caduceus/common/settings.py` | `Settings`/`Timeouts` (upstream_base_url, default_model, binds, timeouts); `from_env()`; `SENTINEL_MODEL="default"` |
| `caduceus/common/logging.py` | structured logger + **bearer-token redaction** (`redact`, `RedactionFilter`) |
| `caduceus/aigateway/routing.py` | **PURE** `resolve_model` (BR-2), `build_route` (v1 upstream; v2 seam via agent_id) |
| `caduceus/aigateway/headers.py` | **PURE** `sanitize_headers` (BR-4 token strip, BR-10 hop-by-hop) |
| `caduceus/aigateway/errors_map.py` | **PURE** `map_error` (BR-7) |
| `caduceus/aigateway/models_augment.py` | **PURE** `augment_models` (BR-8 default alias, dedup) |

## Tests
- `tests/unit/test_routing.py`, `test_errors_map.py`, `test_models_augment.py` (example-based, PBT-10 anchors).
- `tests/pbt/test_aigateway_properties.py` — Hypothesis **P1–P5, P7**.

## PBT outcome (notable)
Property testing surfaced two issues, both resolved:
1. **Test-spec fix**: P4 originally asserted "token substring absent from all values" — false-positives for 1-char tokens. Tightened to assert the **credential phrase** (`Bearer <token>`) never leaks.
2. **Real bug fix**: `redact()` used an ASCII-only character class, so a **non-ASCII token** after "Bearer " was not redacted (log secret-leak). Regex changed to `(?i)(bearer\s+)(\S+)`.

## Change requests applied
- **No personal defaults in code/tests** (user request): removed baked-in `http://localhost:11434/v1` / `your-model` from `settings.py` and all tests. `upstream_base_url` + `default_model` are now **required config** (default `None`); added `Settings.missing_required()` + `ensure_configured()` (raises `ConfigError` with guidance) — the seam for the U4 "prompt if unset, reuse if set" gateway setup (FR-G5). Added `tests/unit/test_settings.py`.

## Requirement traceability
- FR-P1/P2/P3 → routing + models_augment; BR-2/BR-7/BR-8/BR-4/BR-10 implemented; RESILIENCY-10 (error normalization) in `errors_map`.
