"""Shared pytest configuration for fast and integration test groups."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every non-integration test as a fast unit test.

    The default ``pytest`` command excludes tests explicitly marked as
    ``integration`` in ``pytest.ini``. Existing fast tests do not need a marker in
    each file: this hook applies the ``unit`` marker automatically unless a test
    opts into the slower integration group.
    """

    for item in items:
        if item.get_closest_marker("integration") is None:
            item.add_marker(pytest.mark.unit)


_SETTINGS_ENV_VARS = {
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_URL",
    "PUBLISH_INTERVAL_MINUTES",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_IMAGE_MODEL",
    "OPENROUTER_IMAGE_QUALITY",
    "OPENROUTER_IMAGE_SIZE",
    "OPENROUTER_IMAGE_FORMAT",
    "OPENROUTER_BASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID",
    "NEWS_TOPIC",
    "NEWS_LANGUAGE",
    "POST_LANGUAGE",
    "MAX_NEWS_ITEMS",
    "POST_STYLE",
    "POST_MAX_LENGTH",
    "INCLUDE_SOURCE_LINK",
    "INCLUDE_HASHTAGS",
    "ENABLE_IMAGE_GENERATION",
}


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch):
    """Keep startup/runtime environment variables from leaking into unit tests."""

    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    try:
        from app.config import _get_cached_settings
    except ImportError:
        yield
        return

    _get_cached_settings.cache_clear()
    yield
    _get_cached_settings.cache_clear()
