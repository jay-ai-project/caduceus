"""U4 — Settings TOML file layer (env > file > default)."""

from __future__ import annotations

from caduceus.common.settings import Settings


def test_file_provides_values(tmp_path, monkeypatch):
    for k in ("CADUCEUS_UPSTREAM_BASE_URL", "CADUCEUS_DEFAULT_MODEL", "CADUCEUS_CONTROL_BIND"):
        monkeypatch.delenv(k, raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text('upstream_base_url = "http://up/v1"\ndefault_model = "m1"\n', encoding="utf-8")
    s = Settings.from_env_and_file(cfg)
    assert s.upstream_base_url == "http://up/v1"
    assert s.default_model == "m1"
    assert s.missing_required() == []


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('upstream_base_url = "http://file/v1"\ndefault_model = "file-m"\n', encoding="utf-8")
    monkeypatch.setenv("CADUCEUS_UPSTREAM_BASE_URL", "http://env/v1")
    monkeypatch.delenv("CADUCEUS_DEFAULT_MODEL", raising=False)
    s = Settings.from_env_and_file(cfg)
    assert s.upstream_base_url == "http://env/v1"   # env wins
    assert s.default_model == "file-m"               # file fills the gap


def test_missing_when_absent(tmp_path, monkeypatch):
    for k in ("CADUCEUS_UPSTREAM_BASE_URL", "CADUCEUS_DEFAULT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env_and_file(tmp_path / "nope.toml")
    assert set(s.missing_required()) == {"upstream_base_url", "default_model"}


def test_write_then_read_round_trip(tmp_path, monkeypatch):
    for k in ("CADUCEUS_UPSTREAM_BASE_URL", "CADUCEUS_DEFAULT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(upstream_base_url="http://up/v1", default_model="m1")
    cfg = tmp_path / "config.toml"
    s.write_config_toml(cfg)
    loaded = Settings.from_env_and_file(cfg)
    assert loaded.upstream_base_url == "http://up/v1" and loaded.default_model == "m1"
