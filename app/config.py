"""Centralized application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from `.env` and process environment."""

    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(default="sqlite:///./data/publications.db", alias="DATABASE_URL")
    publish_interval_minutes: int = Field(default=30, alias="PUBLISH_INTERVAL_MINUTES", ge=1)

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openai/gpt-4.1-mini", alias="OPENROUTER_MODEL")
    openrouter_base_url: AnyUrl = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_channel_id: str | None = Field(default=None, alias="TELEGRAM_CHANNEL_ID")

    news_topic: str = Field(default="technology", alias="NEWS_TOPIC")
    news_language: str = Field(default="ru", alias="NEWS_LANGUAGE")
    post_language: str = Field(default="ru", alias="POST_LANGUAGE")
    max_news_items: int = Field(default=5, alias="MAX_NEWS_ITEMS", ge=1)
    post_style: str = Field(default="concise", alias="POST_STYLE")
    post_max_length: int = Field(default=1000, alias="POST_MAX_LENGTH", ge=1)
    include_source_link: bool = Field(default=True, alias="INCLUDE_SOURCE_LINK")
    include_hashtags: bool = Field(default=True, alias="INCLUDE_HASHTAGS")
    enable_image_generation: bool = Field(default=False, alias="ENABLE_IMAGE_GENERATION")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def chat_completions_url(self) -> str:
        """OpenRouter chat completions endpoint derived from the base URL."""
        return f"{str(self.openrouter_base_url).rstrip('/')}/chat/completions"

    @field_validator("app_env")
    @classmethod
    def normalize_app_env(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"dev", "test", "prod"}:
            raise ValueError("APP_ENV must be one of: dev, test, prod")
        return normalized

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper().strip()


def get_settings() -> Settings:
    """Return cached application settings."""

    return _get_cached_settings()


@lru_cache
def _get_cached_settings() -> Settings:
    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    """Validate settings required only when the application runs in production."""

    if settings.app_env != "prod":
        return

    required_values = {
        "OPENROUTER_API_KEY": settings.openrouter_api_key,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHANNEL_ID": settings.telegram_channel_id,
    }
    missing = [name for name, value in required_values.items() if not value]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required production settings: {joined}")

    if settings.telegram_bot_token and ":" not in settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be a real bot token in the '<bot_id>:<secret>' format")
