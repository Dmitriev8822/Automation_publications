"""Tests for Telegram publisher without real Telegram API calls."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset
from app.telegram import TelegramPublisher


@dataclass
class FakeMessage:
    message_id: int


class FakeBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent_messages: list[dict] = []
        self.sent_photos: list[dict] = []

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
