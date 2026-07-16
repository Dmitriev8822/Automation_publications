"""Centralized application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./publications.db"
    publish_interval_minutes: int = Field(default=60, ge=1)

    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    telegram_bot_token: str = ""
    telegram_channel_id: str = ""

    news_topic: str = "technology"
    news_language: str = "ru"
    post_language: str = "ru"
    max_news_items: int = Field(default=5, ge=1, le=50)
    post_style: str = "concise, informative, suitable for Telegram"
    post_max_length: int = Field(default=1000, ge=100)
    include_source_link: bool = True
    include_hashtags: bool = True
    enable_image_generation: bool = True

    @field_validator("app_env")
    @classmethod
    def normalize_app_env(cls, value: str) -> str:
        return value.lower().strip()

    @property
    def chat_completions_url(self) -> str:
        return f"{self.openrouter_base_url.rstrip('/')}/chat/completions"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    """Validate secrets required for production runtime."""

    if settings.app_env != "prod":
        return

    missing = []
    if not settings.openrouter_api_key:
        missing.append("OPENROUTER_API_KEY")
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not settings.telegram_channel_id:
        missing.append("TELEGRAM_CHANNEL_ID")

    if missing:
        raise ValidationError.from_exception_data(
            "Settings",
            [
                {
                    "type": "value_error",
                    "loc": (name,),
                    "msg": f"{name} is required in prod mode",
                    "input": None,
                    "ctx": {"error": ValueError(f"{name} is required in prod mode")},
                }
                for name in missing
            ],
        )
