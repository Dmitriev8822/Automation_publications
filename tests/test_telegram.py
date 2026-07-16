from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset
from app.telegram import TelegramPublisher


class FakeBot:
    def __init__(self) -> None:
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return SimpleNamespace(message_id=101)

    def send_photo(self, **kwargs):
        self.calls.append(("send_photo", kwargs))
        return SimpleNamespace(message_id=202)


class FailingBot(FakeBot):
    def send_message(self, **kwargs):
        raise RuntimeError("telegram is unavailable")


def make_settings() -> Settings:
    return Settings(telegram_bot_token="fake-token", telegram_channel_id="@fake_channel")


def make_post() -> GeneratedPost:
    return GeneratedPost(title="Title", text="Generated Telegram post", source_url="https://example.com/news")


def test_publish_text_post_returns_message_id_without_http_requests():
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    message_id = publisher.publish_post(make_post())

    assert message_id == 101
    assert bot.calls == [
        ("send_message", {"chat_id": "@fake_channel", "text": "Generated Telegram post"})
    ]


def test_publish_post_with_image_uses_caption_and_returns_message_id():
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(data=b"fake-png")

    message_id = publisher.publish_post(make_post(), image)

    assert message_id == 202
    method, kwargs = bot.calls[0]
    assert method == "send_photo"
    assert kwargs["chat_id"] == "@fake_channel"
    assert kwargs["caption"] == "Generated Telegram post"
    assert kwargs["photo"].getvalue() == b"fake-png"


def test_publish_post_propagates_telegram_error_with_context():
    publisher = TelegramPublisher(settings=make_settings(), bot=FailingBot())

    with pytest.raises(RuntimeError, match="Failed to publish Telegram post: telegram is unavailable"):
        publisher.publish_post(make_post())


def test_publisher_requires_settings_when_no_fake_bot():
    settings = Settings(telegram_bot_token=None, telegram_channel_id=None)

    with pytest.raises(ValueError, match="TELEGRAM_CHANNEL_ID"):
        TelegramPublisher(settings=settings)
