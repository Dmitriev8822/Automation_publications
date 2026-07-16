from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import telebot

from app.config import Settings, get_settings
from app.schemas import GeneratedPost, ImageAsset


class TelegramPublisher:
    """Publishes generated posts to a Telegram channel through pyTelegramBotAPI."""

    def __init__(self, settings: Settings | None = None, bot: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.channel_id = self.settings.telegram_channel_id
        token = self.settings.telegram_bot_token

        if not self.channel_id:
            raise ValueError("Telegram publishing is not configured: TELEGRAM_CHANNEL_ID is missing")
        if bot is None and not token:
            raise ValueError("Telegram publishing is not configured: TELEGRAM_BOT_TOKEN is missing")

        self.bot = bot or telebot.TeleBot(token)

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        """Publish a text post or an image with caption and return Telegram message id."""
        try:
            message = self._send_photo(post, image) if image is not None else self._send_text(post)
        except Exception as exc:  # noqa: BLE001 - wrap third-party exceptions with context.
            raise RuntimeError(f"Failed to publish Telegram post: {exc}") from exc

        message_id = getattr(message, "message_id", None)
        if message_id is None:
            raise RuntimeError("Failed to publish Telegram post: Telegram response has no message_id")
        return int(message_id)

    def _send_text(self, post: GeneratedPost) -> Any:
        return self.bot.send_message(chat_id=self.channel_id, text=post.text)

    def _send_photo(self, post: GeneratedPost, image: ImageAsset) -> Any:
        photo = self._resolve_photo(image)
        return self.bot.send_photo(chat_id=self.channel_id, photo=photo, caption=post.text)

    @staticmethod
    def _resolve_photo(image: ImageAsset) -> Any:
        if image.data is not None:
            return BytesIO(image.data)
        if image.file_path is not None:
            return Path(image.file_path).open("rb")
        if image.url is not None:
            return image.url
        raise ValueError("ImageAsset must contain data, url, or file_path")
