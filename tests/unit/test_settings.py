"""Settings: upstream/model are required (no baked-in personal defaults)."""

import pytest

from caduceus.common.settings import ConfigError, Settings


def test_no_baked_in_personal_defaults():
    s = Settings()
    assert s.upstream_base_url is None
    assert s.default_model is None


def test_ensure_configured_raises_when_missing():
    with pytest.raises(ConfigError) as exc:
        Settings().ensure_configured()
    msg = str(exc.value)
    assert "upstream_base_url" in msg
    assert "default_model" in msg


def test_ensure_configured_ok_when_set():
    Settings(upstream_base_url="http://x/v1", default_model="m").ensure_configured()  # no raise


def test_missing_required_lists_only_unset():
    s = Settings(upstream_base_url="http://x/v1")
    assert s.missing_required() == ["default_model"]


def test_from_env_reads_without_personal_fallback(monkeypatch):
    monkeypatch.delenv("CADUCEUS_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("CADUCEUS_DEFAULT_MODEL", raising=False)
    s = Settings.from_env()
    assert s.upstream_base_url is None
    assert s.default_model is None

    monkeypatch.setenv("CADUCEUS_UPSTREAM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("CADUCEUS_DEFAULT_MODEL", "env-model")
    s2 = Settings.from_env()
    assert s2.upstream_base_url == "http://env/v1"
    assert s2.default_model == "env-model"
