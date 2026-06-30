"""U6 — property-based tests (PBT-GC1/GC2/GC3).

PBT-GC1: URL validation is total & deterministic (idempotent verdict); well-formed URLs pass.
PBT-GC2: config.toml round-trip preserves unrelated pre-existing keys.
PBT-GC3: applying the same change twice equals applying it once (idempotent).
"""

from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from caduceus.common.dto import GatewayConfigChange
from caduceus.config import gateway_config as gwc

url_st = st.builds(
    lambda h, p: f"http://{h}:{p}/v1",
    st.from_regex(r"[a-z][a-z0-9.\-]{0,20}", fullmatch=True),
    st.integers(min_value=1, max_value=65535),
)
model_st = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 ._:\-]{0,20}", fullmatch=True)
# safe TOML-string values (no quote/backslash/newline/control chars)
val_st = st.from_regex(r"[A-Za-z0-9 ._/:\-]{0,20}", fullmatch=True)
key_st = st.from_regex(r"[a-z_]{1,12}", fullmatch=True).filter(
    lambda k: k not in ("upstream_base_url", "default_model"))


# ---- PBT-GC1 ----
@given(st.text())
def test_validate_url_total_and_idempotent(s):
    def verdict() -> str:
        try:
            gwc.validate_url(s)
            return "ok"
        except ValueError:
            return "err"

    assert verdict() == verdict()  # deterministic / idempotent, never crashes


@given(url_st)
def test_wellformed_urls_pass(u):
    gwc.validate_url(u)  # no raise


# ---- PBT-GC2 ----
@given(st.dictionaries(key_st, val_st, max_size=5), url_st)
def test_round_trip_preserves_unrelated_keys(extra, u):
    base = dict(extra)
    base["default_model"] = "keepme"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        gwc.atomic_write_toml(p, base)
        gwc.apply_to_toml(p, GatewayConfigChange(upstream_base_url=u))
        data = gwc.load_toml(p)
    assert data["upstream_base_url"] == u
    assert data["default_model"] == "keepme"          # untouched key preserved
    for k, v in extra.items():
        assert data[k] == v                            # all unrelated keys preserved


# ---- PBT-GC3 ----
@given(url_st, model_st)
def test_apply_is_idempotent(u, m):
    change = GatewayConfigChange(upstream_base_url=u, default_model=m)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        gwc.apply_to_toml(p, change)
        once = p.read_text(encoding="utf-8")
        gwc.apply_to_toml(p, change)
        twice = p.read_text(encoding="utf-8")
    assert once == twice
    data = tomllib.loads(twice)
    assert data["upstream_base_url"] == u
    assert data["default_model"] == m.strip()
