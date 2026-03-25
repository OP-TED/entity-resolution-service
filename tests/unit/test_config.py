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


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_default_page_size_rejects_non_positive(monkeypatch, value):
    monkeypatch.setenv("DECISION_STORE_DEFAULT_PAGE_SIZE", value)
    from ers import ERSConfigResolver

    cfg = ERSConfigResolver()
    with pytest.raises(ValueError, match="DECISION_STORE_DEFAULT_PAGE_SIZE must be >= 1"):
        _ = cfg.DECISION_STORE_DEFAULT_PAGE_SIZE


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_max_page_size_rejects_non_positive(monkeypatch, value):
    monkeypatch.setenv("DECISION_STORE_MAX_PAGE_SIZE", value)
    from ers import ERSConfigResolver

    cfg = ERSConfigResolver()
    with pytest.raises(ValueError, match="DECISION_STORE_MAX_PAGE_SIZE must be >= 1"):
        _ = cfg.DECISION_STORE_MAX_PAGE_SIZE
