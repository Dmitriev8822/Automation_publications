"""Telegram publishing adapter based on pyTelegramBotAPI."""

from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import telebot

from app.config import Settings, get_settings
from app.schemas import GeneratedPost, ImageAsset


class TelegramBotProtocol(Protocol):
    """Subset of pyTelegramBotAPI methods used by the publisher."""

    def send_message(self, chat_id: str, text: str, **kwargs: Any) -> Any:
        """Send a text message to a chat/channel."""

    def send_photo(self, chat_id: str, photo: Any, **kwargs: Any) -> Any:
        """Send a photo to a chat/channel."""


class TelegramPublisher:
    """Publish generated posts and optional images to a Telegram channel."""

    def __init__(
        self,
        settings: Settings | None = None,
        bot: TelegramBotProtocol | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.channel_id = self._require_setting(
            self.settings.telegram_channel_id,
            "TELEGRAM_CHANNEL_ID is required to publish to Telegram",
        )
        token = self._require_setting(
            self.settings.telegram_bot_token,
            "TELEGRAM_BOT_TOKEN is required to publish to Telegram",
        )
        self.bot = bot or telebot.TeleBot(token)

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        """Publish a generated post with an optional image and return Telegram message id."""

        try:
            if image is None:
                message = self.bot.send_message(chat_id=self.channel_id, text=post.text)
            else:
                photo_context = self._photo_payload(image)
                with photo_context as photo:
                    message = self.bot.send_photo(
                        chat_id=self.channel_id,
                        photo=photo,
                        caption=post.text,
                    )
        except Exception as exc:
            raise RuntimeError(f"Telegram publication failed: {exc}") from exc

        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram publication failed: response does not contain message_id")
        return message_id

    @staticmethod
    def _require_setting(value: str | None, error_message: str) -> str:
        if not value:
            raise ValueError(error_message)
        return value

    @staticmethod
    def _photo_payload(image: ImageAsset):
        if image.data is not None:
            payload = BytesIO(image.data)
            payload.name = "telegram-image"  # pyTelegramBotAPI uses it as multipart filename.
            return nullcontext(payload)
        if image.file_path is not None:
            return Path(image.file_path).open("rb")
        if image.url is not None:
            return nullcontext(str(image.url))
        raise ValueError("ImageAsset must contain data, url, or file_path")
