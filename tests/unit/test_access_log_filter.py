"""ProbeAccessLogFilter — drop hermes backend-probe 404s from the access log."""

from __future__ import annotations

import logging

from caduceus.daemon.gateway import ProbeAccessLogFilter, install_access_log_filter


def _record(path: str, status: int) -> logging.LogRecord:
    # uvicorn AccessFormatter args: (client_addr, method, full_path, http_version, status)
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s", None, None)
    rec.args = ("172.17.0.1:5000", "GET", path, "1.1", status)
    return rec


def test_drops_probe_404s():
    f = ProbeAccessLogFilter()
    for p in ("/api/tags", "/api/show", "/api/v1/models", "/props", "/v1/props",
              "/version", "/v1/models/default"):
        assert f.filter(_record(p, 404)) is False


def test_keeps_useful_paths():
    f = ProbeAccessLogFilter()
    assert f.filter(_record("/v1/models", 200)) is True          # the probe that matters
    assert f.filter(_record("/v1/chat/completions", 200)) is True
    assert f.filter(_record("/agents", 200)) is True
    assert f.filter(_record("/healthz", 200)) is True


def test_keeps_probe_path_with_non_404_status():
    # if one of these ever returns non-404 (e.g. we implement it), keep it visible
    f = ProbeAccessLogFilter()
    assert f.filter(_record("/api/tags", 200)) is True


def test_ignores_query_string():
    f = ProbeAccessLogFilter()
    assert f.filter(_record("/v1/models/default?x=1", 404)) is False


def test_passes_non_access_records():
    f = ProbeAccessLogFilter()
    rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 0, "boot", None, None)
    assert f.filter(rec) is True


def test_install_is_idempotent():
    access = logging.getLogger("uvicorn.access")
    before = len(access.filters)
    install_access_log_filter()
    install_access_log_filter()
    added = [f for f in access.filters if isinstance(f, ProbeAccessLogFilter)]
    assert len(added) == 1
    # cleanup so other tests/loggers aren't affected
    for f in added:
        access.removeFilter(f)
    assert len(access.filters) == before
