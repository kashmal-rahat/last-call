import os

import pytest

# Default 32+ character signing key for test execution
os.environ.setdefault("APP_SIGNING_KEY", "test-signing-key-at-least-32-chars-long-default")


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    """`get_settings()` is cached per process; give every test fresh settings, and refresh them
    whenever a test changes an environment variable through `monkeypatch`."""
    from lastcall_shared.config import get_settings

    get_settings.cache_clear()
    setenv, delenv = monkeypatch.setenv, monkeypatch.delenv

    def setenv_and_refresh(*args, **kwargs):
        setenv(*args, **kwargs)
        get_settings.cache_clear()

    def delenv_and_refresh(*args, **kwargs):
        delenv(*args, **kwargs)
        get_settings.cache_clear()

    monkeypatch.setenv = setenv_and_refresh
    monkeypatch.delenv = delenv_and_refresh
    yield
    get_settings.cache_clear()
