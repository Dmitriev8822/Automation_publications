"""Telegram publishing adapter based on pyTelegramBotAPI."""

from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import telebot
from telebot import types

from app.config import Settings, get_settings
from app.schemas import GeneratedPost, ImageAsset

MANUAL_PUBLISH_BUTTON_TEXT = "📰 Опубликовать новость"


class TelegramBotProtocol(Protocol):
    """Subset of pyTelegramBotAPI methods used by the publisher."""

    def send_message(self, chat_id: str, text: str, **kwargs: Any) -> Any:
        """Send a text message to a chat/channel."""

    def send_photo(self, chat_id: str, photo: Any, **kwargs: Any) -> Any:
        """Send a photo to a chat/channel."""

    def message_handler(self, *args: Any, **kwargs: Any) -> Callable:
        """Register a Telegram message handler."""

    def infinity_polling(self, **kwargs: Any) -> None:
        """Start long polling for incoming bot updates."""


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

    def register_manual_publish_handler(
        self,
        publish_callback: Callable[[Callable[[str], None]], Any],
    ) -> None:
        """Register /start and button handlers for manual publication from the bot chat."""

        @self.bot.message_handler(commands=["start"])
        def handle_start(message: Any) -> None:
            self._send_control_message(
                self._message_chat_id(message),
                "Готов публиковать новости. Нажмите кнопку ниже, чтобы запустить публикацию вручную.",
                reply_markup=self._manual_publish_keyboard(),
            )

        @self.bot.message_handler(func=lambda message: getattr(message, "text", None) == MANUAL_PUBLISH_BUTTON_TEXT)
        def handle_manual_publish(message: Any) -> None:
            chat_id = self._message_chat_id(message)

            def progress(message_text: str) -> None:
                self._send_control_message(chat_id, message_text)

            self._send_control_message(chat_id, "🚀 Запускаю ручную публикацию новости...")
            try:
                result = publish_callback(progress)
            except Exception as exc:
                self._send_control_message(chat_id, f"❌ Публикация завершилась ошибкой: {exc}")
                return

            if result is None:
                self._send_control_message(chat_id, "ℹ️ Публикация не выполнена: нет новых новостей.")
            else:
                self._send_control_message(chat_id, "🎉 Ручная публикация успешно завершена.")

    def start_manual_polling(self) -> None:
        """Start polling for manual publication commands."""

        self.bot.infinity_polling(skip_pending=True)

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

    @staticmethod
    def _manual_publish_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton(MANUAL_PUBLISH_BUTTON_TEXT))
        return keyboard

    def _send_control_message(self, chat_id: str | int, text: str, **kwargs: Any) -> int:
        message = self.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram control message failed: response does not contain message_id")
        return message_id

    @staticmethod
    def _message_chat_id(message: Any) -> int | str:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            raise RuntimeError("Telegram message does not contain chat.id")
        return chat_id
