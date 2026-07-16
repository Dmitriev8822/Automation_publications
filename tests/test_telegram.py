"""Tests for Telegram publisher without real Telegram API calls."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from telebot.apihelper import ApiTelegramException

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset
from app.telegram import MANUAL_PUBLISH_BUTTON_TEXT, TelegramPublisher


@dataclass
class FakeMessage:
    message_id: int


class FakeBot:
    def __init__(self, *, fail: bool = False, polling_error: Exception | None = None) -> None:
        self.fail = fail
        self.polling_error = polling_error
        self.sent_messages: list[dict] = []
        self.sent_photos: list[dict] = []
        self.handlers: list[dict] = []
        self.polling_started = False

    def send_message(self, chat_id: str, text: str, **kwargs):
        if self.fail:
            raise RuntimeError("telegram is unavailable")
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return FakeMessage(message_id=101)

    def send_photo(self, chat_id: str, photo, **kwargs):
        if self.fail:
            raise RuntimeError("telegram is unavailable")
        self.sent_photos.append({"chat_id": chat_id, "photo": photo, **kwargs})
        return FakeMessage(message_id=202)

    def message_handler(self, *args, **kwargs):
        def decorator(func):
            self.handlers.append({"args": args, "kwargs": kwargs, "func": func})
            return func

        return decorator

    def infinity_polling(self, **kwargs):
        if self.polling_error is not None:
            raise self.polling_error
        self.polling_started = True
        self.polling_kwargs = kwargs

    def get_me(self):
        if self.polling_error is not None:
            raise self.polling_error
        return SimpleNamespace(username="test_news_bot", first_name="Test News Bot")


def make_settings(**overrides) -> Settings:
    defaults = {
        "telegram_bot_token": "test-token",
        "telegram_channel_id": "@test_channel",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_post() -> GeneratedPost:
    return GeneratedPost(
        title="AI release",
        text="Telegram-ready post text",
        image_prompt="Editorial AI image",
        source_url="https://example.com/ai-release",
    )


def test_publish_text_post_returns_message_id() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    message_id = publisher.publish_post(make_post())

    assert message_id == 101
    assert bot.sent_messages == [
        {"chat_id": "@test_channel", "text": "Telegram-ready post text"}
    ]
    assert bot.sent_photos == []


def test_publish_post_with_image_returns_message_id() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(data=b"image-bytes", mime_type="image/png")

    message_id = publisher.publish_post(make_post(), image)

    assert message_id == 202
    assert bot.sent_messages == []
    assert len(bot.sent_photos) == 1
    sent_photo = bot.sent_photos[0]
    assert sent_photo["chat_id"] == "@test_channel"
    assert sent_photo["caption"] == "Telegram-ready post text"
    assert sent_photo["photo"].getvalue() == b"image-bytes"


def test_publish_post_with_image_url() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(url="https://example.com/image.png")

    message_id = publisher.publish_post(make_post(), image)

    assert message_id == 202
    assert bot.sent_photos[0]["photo"] == "https://example.com/image.png"


def test_publish_post_propagates_telegram_error_with_clear_message() -> None:
    publisher = TelegramPublisher(settings=make_settings(), bot=FakeBot(fail=True))

    with pytest.raises(RuntimeError, match="Telegram publication failed: telegram is unavailable"):
        publisher.publish_post(make_post())


def test_missing_settings_raise_clear_error() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_CHANNEL_ID is required"):
        TelegramPublisher(
            settings=make_settings(telegram_channel_id=None),
            bot=FakeBot(),
        )


def test_publisher_uses_injected_bot_without_real_http_requests() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    assert publisher.publish_post(make_post()) == 101
    assert len(bot.sent_messages) == 1


def test_register_manual_publish_handler_sends_button_and_progress_messages() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    progress_messages: list[str] = []

    def publish_callback(progress):
        progress("🔎 fake progress")
        progress_messages.append("called")
        return object()

    publisher.register_manual_publish_handler(publish_callback)

    start_handler = bot.handlers[0]["func"]
    publish_handler = bot.handlers[1]["func"]
    message = SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT)

    start_handler(message)
    publish_handler(message)

    assert len(bot.handlers) == 2
    assert bot.sent_messages[0]["chat_id"] == 555
    assert "Нажмите кнопку" in bot.sent_messages[0]["text"]
    assert bot.sent_messages[1]["text"] == "🚀 Запускаю ручную публикацию новости..."
    assert bot.sent_messages[2]["text"] == "🔎 fake progress"
    assert bot.sent_messages[-1]["text"] == "🎉 Ручная публикация успешно завершена."
    assert progress_messages == ["called"]


def test_manual_publish_handler_reports_no_news() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    publisher.register_manual_publish_handler(lambda progress: None)

    publish_handler = bot.handlers[1]["func"]
    publish_handler(SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT))

    assert bot.sent_messages[-1]["text"] == "ℹ️ Публикация не выполнена: нет новых новостей."


def test_manual_publish_handler_reports_error_without_reraising() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    def fail_publish(progress):
        raise RuntimeError("openrouter unavailable")

    publisher.register_manual_publish_handler(fail_publish)
    publish_handler = bot.handlers[1]["func"]

    publish_handler(SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT))

    assert bot.sent_messages[-1]["text"] == "❌ Публикация завершилась ошибкой: openrouter unavailable"


def test_start_manual_polling_delegates_to_bot() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    publisher.start_manual_polling()

    assert bot.polling_started is True
    assert bot.polling_kwargs == {"skip_pending": True}


def test_start_manual_polling_reports_invalid_token_clearly() -> None:
    error = ApiTelegramException(
        "getUpdates",
        object(),
        {"ok": False, "error_code": 401, "description": "Unauthorized"},
    )
    bot = FakeBot(polling_error=error)
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    with pytest.raises(RuntimeError, match="Check TELEGRAM_BOT_TOKEN"):
        publisher.start_manual_polling()


def test_validate_bot_token_returns_bot_username() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    assert publisher.validate_bot_token() == "@test_news_bot"


def test_validate_bot_token_reports_invalid_token_clearly() -> None:
    error = ApiTelegramException(
        "getMe",
        object(),
        {"ok": False, "error_code": 401, "description": "Unauthorized"},
    )
    bot = FakeBot(polling_error=error)
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    with pytest.raises(RuntimeError, match="python app/main.py --check-telegram"):
        publisher.validate_bot_token()
