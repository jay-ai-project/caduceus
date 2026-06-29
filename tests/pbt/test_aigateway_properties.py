"""Property-based tests (Hypothesis) for U1 pure logic — PBT-01 properties P1–P5, P7.

P6 (stream/unary equivalence oracle) lives in tests/unit/test_app_aigateway.py
because it exercises the async app against the stub upstream.
"""

from __future__ import annotations

import httpx
from hypothesis import given
from hypothesis import strategies as st

from caduceus.aigateway.errors_map import map_error
from caduceus.aigateway.headers import sanitize_headers
from caduceus.aigateway.models_augment import augment_models
from caduceus.aigateway.routing import resolve_model
from caduceus.common.logging import redact
from caduceus.common.settings import SENTINEL_MODEL

D = "stub-model"  # neutral test default model (no personal value baked in)

# Realistic token characters (letters/digits + . _ -)
_token = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="._-"),
    min_size=1,
    max_size=64,
)
_non_sentinel = st.text(max_size=64).filter(lambda s: s.strip().lower() != SENTINEL_MODEL)


@given(st.sampled_from(["default", "DEFAULT", "Default", " default ", "\tdefault\n", None]))
def test_p1_sentinel_resolves_to_default(model):
    assert resolve_model(model, D) == D


@given(_non_sentinel)
def test_p2_non_sentinel_passthrough(model):
    assert resolve_model(model, D) == model


@given(st.one_of(st.none(), st.text(max_size=64)))
def test_p3_idempotent(model):
    once = resolve_model(model, D)
    assert resolve_model(once, D) == once


@given(_token)
def test_p4_token_never_leaks(token):
    bearer = f"Bearer {token}"
    headers = {"Authorization": bearer, "X-Trace": "trace-id", "Content-Type": "application/json"}
    out = sanitize_headers(headers)
    # Authorization (agent token) is stripped...
    assert "authorization" not in {k.lower() for k in out}
    # ...and the bearer credential phrase is not forwarded in any header value.
    assert all(bearer not in v for v in out.values())
    # ...and log redaction removes the credential phrase from a log line.
    line = redact(f"upstream call with Authorization: {bearer}")
    assert bearer not in line
    assert "[REDACTED]" in line


@given(
    st.sampled_from(
        [
            httpx.ConnectError("x"),
            httpx.ReadTimeout("x"),
            httpx.PoolTimeout("x"),
            httpx.ConnectTimeout("x"),
            ValueError("x"),
            RuntimeError("y"),
        ]
    )
)
def test_p5_errors_are_well_formed(exc):
    err = map_error(exc)
    assert err.http_status in {400, 401, 500, 502, 504}
    payload = err.to_openai()["error"]
    assert payload["message"]
    assert payload["type"]


_model_item = st.fixed_dictionaries({"id": st.text(min_size=1, max_size=20), "object": st.just("model")})
_model_list = st.fixed_dictionaries({"object": st.just("list"), "data": st.lists(_model_item, max_size=8)})


@given(st.one_of(st.none(), _model_list))
def test_p7_default_alias_invariant(upstream_models):
    out = augment_models(upstream_models)
    out_ids = [m["id"] for m in out["data"]]
    orig_ids = [
        m.get("id")
        for m in (upstream_models or {}).get("data", [])
        if isinstance(m, dict)
    ]
    assert "default" in out_ids
    if "default" in orig_ids:
        # already present -> unchanged (no duplicate added)
        assert out_ids.count("default") == orig_ids.count("default")
    else:
        assert out_ids.count("default") == 1
