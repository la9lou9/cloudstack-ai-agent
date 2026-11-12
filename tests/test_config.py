import pytest

from cloudstack_agent import config


def test_mock_is_default_without_credentials(monkeypatch):
    for name in ("CLOUDSTACK_URL", "CLOUDSTACK_API_KEY", "CLOUDSTACK_SECRET_KEY", "CLOUDSTACK_MOCK"):
        monkeypatch.delenv(name, raising=False)
    assert config.load_settings().mock is True


def test_real_mode_requires_all_three_credentials(monkeypatch):
    monkeypatch.setenv("CLOUDSTACK_MOCK", "false")
    monkeypatch.setenv("CLOUDSTACK_URL", "https://cloud.example.com")
    monkeypatch.delenv("CLOUDSTACK_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDSTACK_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="requires CLOUDSTACK_URL"):
        config.load_settings()


def test_write_tools_are_off_by_default(monkeypatch):
    for name in ("CLOUDSTACK_URL", "CLOUDSTACK_API_KEY", "CLOUDSTACK_SECRET_KEY", "CLOUDSTACK_AGENT_ALLOW_WRITE"):
        monkeypatch.delenv(name, raising=False)
    assert config.load_settings().allow_write is False
