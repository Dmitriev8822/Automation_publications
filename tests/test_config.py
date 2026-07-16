import pytest
from pydantic import ValidationError

from app.config import Settings, validate_runtime_settings


def test_default_values():
    settings = Settings(_env_file=None)

    assert settings.app_env == "dev"
    assert settings.log_level == "INFO"
    assert settings.database_url == "sqlite:///./data/publications.db"
    assert settings.publish_interval_minutes == 30
    assert settings.openrouter_api_key is None
    assert settings.openrouter_model == "openai/gpt-4.1-mini"
    assert str(settings.openrouter_base_url).rstrip("/") == "https://openrouter.ai/api/v1"
    assert settings.telegram_bot_token is None
    assert settings.telegram_channel_id is None
    assert settings.news_topic == "technology"
    assert settings.news_language == "ru"
    assert settings.post_language == "ru"
    assert settings.max_news_items == 5
    assert settings.post_style == "concise"
    assert settings.post_max_length == 1000
    assert settings.include_source_link is True
    assert settings.include_hashtags is True
    assert settings.enable_image_generation is False


def test_environment_variable_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("PUBLISH_INTERVAL_MINUTES", "10")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.com/api")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-telegram-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test_channel")
    monkeypatch.setenv("NEWS_TOPIC", "science")
    monkeypatch.setenv("NEWS_LANGUAGE", "en")
    monkeypatch.setenv("POST_LANGUAGE", "en")
    monkeypatch.setenv("MAX_NEWS_ITEMS", "3")
    monkeypatch.setenv("POST_STYLE", "friendly")
    monkeypatch.setenv("POST_MAX_LENGTH", "500")
    monkeypatch.setenv("INCLUDE_SOURCE_LINK", "false")
    monkeypatch.setenv("INCLUDE_HASHTAGS", "false")
    monkeypatch.setenv("ENABLE_IMAGE_GENERATION", "true")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == "sqlite:///:memory:"
    assert settings.publish_interval_minutes == 10
    assert settings.openrouter_api_key == "test-openrouter-key"
    assert settings.openrouter_model == "test/model"
    assert str(settings.openrouter_base_url).rstrip("/") == "https://example.com/api"
    assert settings.telegram_bot_token == "test-telegram-token"
    assert settings.telegram_channel_id == "@test_channel"
    assert settings.news_topic == "science"
    assert settings.news_language == "en"
    assert settings.post_language == "en"
    assert settings.max_news_items == 3
    assert settings.post_style == "friendly"
    assert settings.post_max_length == 500
    assert settings.include_source_link is False
    assert settings.include_hashtags is False
    assert settings.enable_image_generation is True


def test_prod_requires_openrouter_and_telegram_settings():
    settings = Settings(APP_ENV="prod", _env_file=None)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY") as exc_info:
        validate_runtime_settings(settings)

    assert "TELEGRAM_BOT_TOKEN" in str(exc_info.value)
    assert "TELEGRAM_CHANNEL_ID" in str(exc_info.value)


def test_prod_rejects_malformed_telegram_token():
    settings = Settings(
        APP_ENV="prod",
        OPENROUTER_API_KEY="test-openrouter-key",
        TELEGRAM_BOT_TOKEN="not-a-real-token",
        TELEGRAM_CHANNEL_ID="@test_channel",
        _env_file=None,
    )

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN.*<bot_id>:<secret>"):
        validate_runtime_settings(settings)


def test_dev_allows_missing_secrets():
    settings = Settings(APP_ENV="dev", _env_file=None)

    validate_runtime_settings(settings)


def test_test_env_allows_missing_secrets():
    settings = Settings(APP_ENV="test", _env_file=None)

    validate_runtime_settings(settings)


def test_invalid_app_env_fails_validation():
    with pytest.raises(ValidationError):
        Settings(APP_ENV="staging", _env_file=None)
