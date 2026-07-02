"""Property-based tests for U11 (agent dashboard routing): PBT-U11-1..3.

- PBT-U11-1  proxy URL totality — any path/query joins under the pinned
             loopback authority, never raising (BR-DB5).
- PBT-U11-2  hop-by-hop filter — no RFC-7230 hop-by-hop header (fixed set or
             Connection-nominated) survives; end-to-end headers are preserved
             verbatim and in order (BR-DB7).
- PBT-U11-3  secret non-exposure — dashboard_password never appears in the
             AgentView projection (BR-DB2).
"""

from __future__ import annotations

import json
from dataclasses import replace

from hypothesis import assume, given
from hypothesis import strategies as st

from caduceus.common.dto import AgentView
from caduceus.common.models import AgentKind, AgentRecord, Lifecycle
from caduceus.daemon.dashboard_proxy import HOP_BY_HOP, filter_headers, upstream_url

_ports = st.integers(min_value=1, max_value=65535)
_paths = st.text(max_size=200)
_queries = st.text(alphabet=st.characters(exclude_characters="#"), max_size=100)


# ---- PBT-U11-1: proxy URL totality --------------------------------
@given(port=_ports, path=_paths, query=_queries,
       scheme=st.sampled_from(["http", "ws"]))
def test_pbt_u11_1_upstream_url_totality(port, path, query, scheme):
    url = upstream_url(scheme, port, path, query)
    prefix = f"{scheme}://127.0.0.1:{port}/"
    assert url.startswith(prefix)
    # nothing between authority and path — the authority can never be extended
    assert url[len(prefix) - 1] == "/"


# ---- PBT-U11-2: hop-by-hop filter ----------------------------------
_token = st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126,
                                        exclude_characters=",;:"), min_size=1, max_size=16)
_header_name = st.one_of(_token, st.sampled_from(sorted(HOP_BY_HOP) + ["Host", "Cookie"]))
_headers = st.lists(st.tuples(_header_name, _token), max_size=20)
_nominated = st.lists(_token, max_size=4)


@given(headers=_headers, nominated=_nominated, drop_host=st.booleans())
def test_pbt_u11_2_hop_by_hop_filter(headers, nominated, drop_host):
    if nominated:
        headers = headers + [("Connection", ", ".join(nominated))]
    out = filter_headers(headers, drop_host=drop_host)

    # ALL Connection headers nominate tokens — including any that the random
    # header list itself contains, not just the ones this test appended.
    all_nominated = {t.strip().lower()
                     for k, v in headers if k.lower() == "connection"
                     for t in v.split(",") if t.strip()}
    banned = set(HOP_BY_HOP) | all_nominated
    if drop_host:
        banned.add("host")
    assert all(k.lower() not in banned for k, _ in out)
    # end-to-end headers pass through verbatim, order preserved
    expected = [(k, v) for k, v in headers if k.lower() not in banned]
    assert out == expected


# ---- PBT-U11-3: secret non-exposure --------------------------------
_secrets = st.text(min_size=8, max_size=40).filter(lambda s: s.strip())


@given(password=_secrets, port=st.one_of(st.none(), _ports),
       name=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True))
def test_pbt_u11_3_password_never_in_view(password, port, name):
    rec = AgentRecord(name=name, kind=AgentKind.local, token="tok",
                      dashboard_port=port, dashboard_password=password,
                      lifecycle=Lifecycle.running)
    # Guard against a coincidental substring (password ⊆ some non-secret field):
    # the property is "the password field leaks nothing", not "no collision".
    baseline = json.dumps(AgentView.from_record(
        replace(rec, dashboard_password=None)).to_dict())
    assume(password not in baseline)
    view_json = json.dumps(AgentView.from_record(rec).to_dict())
    assert password not in view_json
    # and the flag reflects only the port's presence
    assert AgentView.from_record(rec).dashboard is (port is not None)
