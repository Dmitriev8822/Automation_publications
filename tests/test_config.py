import pytest

from app.config import Settings, validate_runtime_settings


def test_settings_defaults_are_dev_friendly():
    settings = Settings(_env_file=None)

    assert settings.app_env == "dev"
    assert settings.database_url == "sqlite:///./app.db"
    assert settings.publish_interval_minutes == 30


def test_prod_requires_external_service_settings():
    settings = Settings(APP_ENV="prod", _env_file=None)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        validate_runtime_settings(settings)


def test_dev_does_not_require_external_service_settings():
    settings = Settings(APP_ENV="dev", _env_file=None)

    validate_runtime_settings(settings)
