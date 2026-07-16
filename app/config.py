"""Application settings loaded from environment variables and .env files."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration shared by all modules."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(default="sqlite:///./app.db", alias="DATABASE_URL")
    publish_interval_minutes: int = Field(default=30, ge=1, alias="PUBLISH_INTERVAL_MINUTES")

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str | None = Field(default=None, alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_channel_id: str | None = Field(default=None, alias="TELEGRAM_CHANNEL_ID")

    news_topic: str = Field(default="automation", alias="NEWS_TOPIC")
    news_language: str = Field(default="en", alias="NEWS_LANGUAGE")
    post_language: str = Field(default="ru", alias="POST_LANGUAGE")
    max_news_items: int = Field(default=5, ge=1, alias="MAX_NEWS_ITEMS")
    post_style: str = Field(default="telegram_news", alias="POST_STYLE")
    post_max_length: int = Field(default=1000, ge=100, alias="POST_MAX_LENGTH")
    include_source_link: bool = Field(default=True, alias="INCLUDE_SOURCE_LINK")
    include_hashtags: bool = Field(default=True, alias="INCLUDE_HASHTAGS")
    enable_image_generation: bool = Field(default=False, alias="ENABLE_IMAGE_GENERATION")

    @field_validator("openrouter_api_key", "openrouter_model", "telegram_bot_token", "telegram_channel_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    """Validate settings required for the selected runtime environment."""

    if settings.app_env != "prod":
        return

    required = {
        "OPENROUTER_API_KEY": settings.openrouter_api_key,
        "OPENROUTER_MODEL": settings.openrouter_model,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHANNEL_ID": settings.telegram_channel_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required production settings: {', '.join(missing)}")
