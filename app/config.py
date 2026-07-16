"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./automation_publications.db"
    publish_interval_minutes: int = 30
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    news_topic: str = "technology"
    news_language: str = "ru"
    post_language: str = "ru"
    max_news_items: int = 5
    post_style: str = "concise"
    post_max_length: int = 1000
    include_source_link: bool = True
    include_hashtags: bool = True
    enable_image_generation: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    if settings.app_env.lower() == "prod":
        missing = []
        if not settings.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        if not settings.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not settings.telegram_channel_id:
            missing.append("TELEGRAM_CHANNEL_ID")
        if missing:
            raise ValueError("Missing required production settings: " + ", ".join(missing))
