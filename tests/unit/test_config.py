import pytest

from ers import config


def test_defaults():
    assert config.DECISION_STORE_MAX_CANDIDATES == 5
    assert config.DECISION_STORE_DEFAULT_PAGE_SIZE == 250
    assert config.DECISION_STORE_MAX_PAGE_SIZE == 1000


def test_env_override_max_candidates(monkeypatch):
    monkeypatch.setenv("DECISION_STORE_MAX_CANDIDATES", "10")
    from ers import ERSConfigResolver

    cfg = ERSConfigResolver()
    assert cfg.DECISION_STORE_MAX_CANDIDATES == 10


def test_env_override_default_page_size(monkeypatch):
    monkeypatch.setenv("DECISION_STORE_DEFAULT_PAGE_SIZE", "100")
    from ers import ERSConfigResolver

    cfg = ERSConfigResolver()
    assert cfg.DECISION_STORE_DEFAULT_PAGE_SIZE == 100


def test_env_override_max_page_size(monkeypatch):
    monkeypatch.setenv("DECISION_STORE_MAX_PAGE_SIZE", "500")
    from ers import ERSConfigResolver

    cfg = ERSConfigResolver()
    assert cfg.DECISION_STORE_MAX_PAGE_SIZE == 500
