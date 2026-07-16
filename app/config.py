from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./publications.db"
    publish_interval_minutes: int = 60
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None
    news_topic: str = "technology"
    news_language: str = "ru"
    post_language: str = "ru"
    max_news_items: int = 10
    post_style: str = "concise"
    post_max_length: int = 4096
    include_source_link: bool = True
    include_hashtags: bool = True
    enable_image_generation: bool = True


def validate_runtime_settings(settings: Settings) -> None:
    if settings.app_env.lower() == "prod":
        missing = [
            name
            for name, value in {
                "OPENROUTER_API_KEY": settings.openrouter_api_key,
                "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
                "TELEGRAM_CHANNEL_ID": settings.telegram_channel_id,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required production settings: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
