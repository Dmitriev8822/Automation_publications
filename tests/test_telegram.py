"""Tests for Telegram publisher without real Telegram API calls."""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest
from telebot.apihelper import ApiTelegramException

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset
from app.telegram import (
    MANUAL_PUBLISH_BUTTON_TEXT,
    START_INSTRUCTION_TEXT,
    TelegramPublisher,
)


@dataclass
class FakeMessage:
    message_id: int


class FakeBot:
    def __init__(
        self,
        *,
        fail: bool = False,
        photo_error: Exception | None = None,
        polling_error: Exception | None = None,
    ) -> None:
        self.fail = fail
        self.photo_error = photo_error
        self.polling_error = polling_error
        self.sent_messages: list[dict] = []
        self.sent_photos: list[dict] = []
        self.handlers: list[dict] = []
        self.commands: list = []
        self.polling_started = False

    def send_message(self, chat_id: str, text: str, **kwargs):
        if self.fail:
            raise RuntimeError("telegram is unavailable")
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return FakeMessage(message_id=101)

    def send_photo(self, chat_id: str, photo, **kwargs):
        if self.photo_error is not None:
            raise self.photo_error
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

    def set_my_commands(self, commands):
        self.commands = commands
        return True


def make_settings(**overrides) -> Settings:
    defaults = {
        "telegram_bot_token": "test-token",
        "telegram_channel_id": "@test_channel",
    }
    defaults.update(overrides)
    return Settings(**defaults, _env_file=None)


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


def test_publish_post_with_image_uses_mime_type_extension() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(data=b"image-bytes", mime_type="image/png")

    publisher.publish_post(make_post(), image)

    assert bot.sent_photos[0]["photo"].name == "telegram-image.png"


def test_publish_post_with_long_text_keeps_image_caption_and_sends_full_text() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    post = make_post().model_copy(update={"text": "x" * 1100})
    image = ImageAsset(data=b"image-bytes", mime_type="image/jpeg")

    message_id = publisher.publish_post(post, image)

    assert message_id == 202
    assert len(bot.sent_photos) == 1
    assert len(bot.sent_photos[0]["caption"]) == 1024
    assert bot.sent_photos[0]["caption"].endswith("…")
    assert bot.sent_messages == [{"chat_id": "@test_channel", "text": "x" * 1100}]
    assert bot.sent_photos[0]["photo"].name == "telegram-image.jpg"


def test_publish_post_with_image_url_downloads_and_uploads_bytes() -> None:
    bot = FakeBot()
    fetched_urls: list[str] = []

    def fetch_image(url: str) -> tuple[bytes, str | None]:
        fetched_urls.append(url)
        return b"downloaded-image", "image/png"

    publisher = TelegramPublisher(
        settings=make_settings(), bot=bot, image_url_fetcher=fetch_image
    )
    image = ImageAsset(url="https://example.com/image.png")

    message_id = publisher.publish_post(make_post(), image)

    assert message_id == 202
    assert fetched_urls == ["https://example.com/image.png"]
    sent_photo = bot.sent_photos[0]["photo"]
    assert sent_photo.getvalue() == b"downloaded-image"
    assert sent_photo.name == "telegram-image.png"


def test_publish_post_falls_back_to_text_when_telegram_cannot_process_image() -> None:
    image_error = ApiTelegramException(
        "sendPhoto",
        object(),
        {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: IMAGE_PROCESS_FAILED",
        },
    )
    bot = FakeBot(photo_error=image_error)
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(data=b"invalid-image-bytes", mime_type="image/jpeg")

    message_id = publisher.publish_post(make_post(), image)

    assert message_id == 101
    assert bot.sent_photos == []
    assert bot.sent_messages == [
        {"chat_id": "@test_channel", "text": "Telegram-ready post text"}
    ]


def test_publish_post_propagates_telegram_error_with_clear_message() -> None:
    publisher = TelegramPublisher(settings=make_settings(), bot=FakeBot(fail=True))

    with pytest.raises(
        RuntimeError, match="Telegram publication failed: telegram is unavailable"
    ):
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
    message = SimpleNamespace(
        chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT
    )

    start_handler(message)
    publish_handler(message)

    assert len(bot.handlers) == 2
    assert bot.sent_messages[0]["chat_id"] == 555
    assert "Как пользоваться ботом" in bot.sent_messages[0]["text"]
    assert MANUAL_PUBLISH_BUTTON_TEXT in bot.sent_messages[0]["text"]
    assert bot.sent_messages[1]["text"] == "🚀 Запускаю ручную публикацию новости..."
    assert bot.sent_messages[2]["text"] == "🔎 fake progress"
    assert bot.sent_messages[-1]["text"] == "🎉 Ручная публикация успешно завершена."
    assert progress_messages == ["called"]


def test_start_command_sends_bot_usage_instruction_with_main_menu() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    publisher.register_manual_publish_handler(
        lambda progress: make_manual_draft(),
        lambda draft: None,
        lambda draft: draft,
        lambda draft: draft,
    )
    bot.handlers[0]["func"](
        SimpleNamespace(chat=SimpleNamespace(id=555), text="/start")
    )

    assert bot.sent_messages[-1]["text"] == START_INSTRUCTION_TEXT
    assert "Как пользоваться ботом" in bot.sent_messages[-1]["text"]
    assert "/menu" in bot.sent_messages[-1]["text"]
    assert bot.sent_messages[-1]["reply_markup"] is not None


def test_register_manual_publish_handler_sets_start_and_menu_quick_commands() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    publisher.register_manual_publish_handler(lambda progress: None)

    assert [(command.command, command.description) for command in bot.commands] == [
        ("start", "Открыть главное меню"),
        ("menu", "Показать меню"),
    ]


def test_manual_publish_handler_reports_no_news() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    publisher.register_manual_publish_handler(lambda progress: None)

    publish_handler = bot.handlers[1]["func"]
    publish_handler(
        SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT)
    )

    assert (
        bot.sent_messages[-1]["text"]
        == "ℹ️ Публикация не выполнена: нет новых новостей."
    )


def test_manual_publish_handler_reports_error_without_reraising() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    def fail_publish(progress):
        raise RuntimeError("openrouter unavailable")

    publisher.register_manual_publish_handler(fail_publish)
    publish_handler = bot.handlers[1]["func"]

    publish_handler(
        SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT)
    )

    assert (
        bot.sent_messages[-1]["text"]
        == "❌ Публикация завершилась ошибкой: openrouter unavailable"
    )


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


from app.telegram import (
    CONTENT_PLAN_BUTTON_TEXT,
    REMINDERS_BUTTON_TEXT,
    APPROVE_REMINDER_BUTTON_TEXT,
    REJECT_REMINDER_BUTTON_TEXT,
)
from app.schemas import ContentPlan, ContentPlanItem
from datetime import datetime, timezone


def make_plan() -> ContentPlan:
    now = datetime.now(timezone.utc)
    return ContentPlan(
        title="План",
        period_start=now,
        period_end=now,
        items=[
            ContentPlanItem(
                scheduled_at=now, title="Пост", text="Текст", image_prompt="Картинка"
            )
        ],
    )


def dispatch_text(bot: FakeBot, chat_id: int, text: str) -> None:
    message = SimpleNamespace(chat=SimpleNamespace(id=chat_id), text=text)
    for handler in bot.handlers:
        predicate = handler["kwargs"].get("func")
        commands = handler["kwargs"].get("commands")
        if commands is not None:
            command = text.removeprefix("/") if text.startswith("/") else None
            if command in commands:
                handler["func"](message)
                return
            continue
        if predicate is not None and predicate(message):
            handler["func"](message)
            return
    raise AssertionError(f"No handler matched text: {text}")


def test_content_plan_dialog_passes_follow_up_context_until_approval() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    calls: list[tuple[str, list[str]]] = []
    approved: list[ContentPlan] = []

    def generate(description: str, context: list[str] | None = None) -> ContentPlan:
        calls.append((description, list(context or [])))
        return make_plan()

    publisher.register_content_plan_handler(generate, approved.append)
    start_handler = bot.handlers[0]["func"]
    dialog_handler = bot.handlers[1]["func"]
    chat = SimpleNamespace(id=555)

    start_handler(SimpleNamespace(chat=chat, text=CONTENT_PLAN_BUTTON_TEXT))
    dialog_handler(SimpleNamespace(chat=chat, text="план на неделю"))
    dialog_handler(SimpleNamespace(chat=chat, text="добавь больше продающих тем"))
    dialog_handler(SimpleNamespace(chat=chat, text="✅ Согласовать"))

    assert calls[0] == ("план на неделю", [])
    assert calls[1][0] == "план на неделю"
    assert any("добавь больше продающих тем" in item for item in calls[1][1])
    assert len(approved) == 1


def test_menu_buttons_interrupt_active_dialogs_without_cross_handling() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    content_plan_calls: list[tuple[str, list[str]]] = []
    reminder_settings: list[tuple[int | None, int | str]] = []

    def generate(description: str, context: list[str] | None = None) -> ContentPlan:
        content_plan_calls.append((description, list(context or [])))
        return make_plan()

    publisher.register_content_plan_handler(generate, lambda plan: None)
    publisher.register_reminders_handler(
        lambda minutes, chat_id: reminder_settings.append((minutes, chat_id))
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, REMINDERS_BUTTON_TEXT)
    dispatch_text(bot, 555, "15")

    assert content_plan_calls == []
    assert reminder_settings == [(15, 555)]
    assert "сейчас напоминания отключены" in bot.sent_messages[-2]["text"]
    assert "переустановить таймер" in bot.sent_messages[-2]["text"]
    assert "Напомню за 15 минут" in bot.sent_messages[-1]["text"]

    dispatch_text(bot, 555, REMINDERS_BUTTON_TEXT)
    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, "план на неделю")

    assert content_plan_calls == [("план на неделю", [])]


def test_reminders_dialog_saves_minutes_and_approval_handler_confirms_publication() -> (
    None
):
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    configured: list[tuple[int | None, int | str]] = []
    approved: list[int] = []

    publisher.register_reminders_handler(
        lambda minutes, chat_id: configured.append((minutes, chat_id))
    )
    publisher.register_publication_approval_handler(
        approved.append,
        lambda item_id: None,
        lambda item_id: make_plan().items[0],
        lambda item_id: make_plan().items[0],
    )
    reminders_start = bot.handlers[0]["func"]
    reminders_dialog = bot.handlers[1]["func"]
    approval_handler = bot.handlers[2]["func"]
    chat = SimpleNamespace(id=777)

    reminders_start(SimpleNamespace(chat=chat, text=REMINDERS_BUTTON_TEXT))
    reminders_dialog(SimpleNamespace(chat=chat, text="15"))
    publisher.send_publication_reminder(777, 42, make_plan().items[0])
    approval_handler(SimpleNamespace(chat=chat, text=APPROVE_REMINDER_BUTTON_TEXT))

    assert publisher.reminder_minutes_before == 15
    assert publisher.reminder_chat_id == 777
    assert configured == [(15, 777)]
    assert approved == [42]
    assert bot.sent_messages[-1]["text"] == "✅ Пост одобрен и опубликован в канале."


def test_reminders_dialog_supports_preset_and_custom_minutes() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    configured: list[tuple[int | None, int | str]] = []

    publisher.reminder_minutes_before = 30
    publisher.register_reminders_handler(
        lambda minutes, chat_id: configured.append((minutes, chat_id))
    )

    dispatch_text(bot, 777, REMINDERS_BUTTON_TEXT)
    assert "сейчас стоит таймер за 30 минут" in bot.sent_messages[-1]["text"]
    dispatch_text(bot, 777, "За 1 час")
    assert publisher.reminder_minutes_before == 60
    assert configured == [(60, 777)]

    dispatch_text(bot, 777, REMINDERS_BUTTON_TEXT)
    dispatch_text(bot, 777, "другое")
    dispatch_text(bot, 777, "45")

    assert publisher.reminder_minutes_before == 45
    assert configured == [(60, 777), (45, 777)]
    assert "Напомню за 45 минут" in bot.sent_messages[-1]["text"]


def test_reminders_dialog_can_disable_persistent_reminders() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    configured: list[tuple[int | None, int | str]] = []

    publisher.register_reminders_handler(
        lambda minutes, chat_id: configured.append((minutes, chat_id))
    )
    reminders_start = bot.handlers[0]["func"]
    reminders_dialog = bot.handlers[1]["func"]
    chat = SimpleNamespace(id=777)

    reminders_start(SimpleNamespace(chat=chat, text=REMINDERS_BUTTON_TEXT))
    reminders_dialog(SimpleNamespace(chat=chat, text="0"))

    assert publisher.reminder_minutes_before is None
    assert publisher.reminder_chat_id == 777
    assert configured == [(None, 777)]
    assert "Напоминания отключены" in bot.sent_messages[-1]["text"]


def test_content_plan_dialog_reports_generation_error_without_reraising() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    def fail_generate(
        description: str, context: list[str] | None = None
    ) -> ContentPlan:
        raise RuntimeError("OpenRouter request failed")

    publisher.register_content_plan_handler(fail_generate, lambda plan: None)
    start_handler = bot.handlers[0]["func"]
    dialog_handler = bot.handlers[1]["func"]
    chat = SimpleNamespace(id=555)

    start_handler(SimpleNamespace(chat=chat, text=CONTENT_PLAN_BUTTON_TEXT))
    dialog_handler(SimpleNamespace(chat=chat, text="план на неделю"))

    assert "Не удалось сформировать контент план" in bot.sent_messages[-1]["text"]
    assert "OpenRouter request failed" in bot.sent_messages[-1]["text"]


def test_content_plan_publication_reminder_sends_image_preview() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    image = ImageAsset(data=b"image-bytes", mime_type="image/png")

    message_id = publisher.send_publication_reminder(
        777, 42, make_plan().items[0], image
    )

    assert message_id == 202
    assert bot.sent_photos
    assert bot.sent_photos[-1]["chat_id"] == 777
    assert "Скоро публикация #42" in bot.sent_photos[-1]["caption"]
    assert bot.sent_photos[-1]["reply_markup"] is not None


def test_publication_approval_handler_matches_persisted_string_chat_id() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    rejected: list[int] = []

    publisher.register_publication_approval_handler(
        lambda item_id: None,
        rejected.append,
        lambda item_id: make_plan().items[0],
        lambda item_id: make_plan().items[0],
    )
    approval_handler = bot.handlers[0]["func"]

    publisher.send_publication_reminder("777", 42, make_plan().items[0])
    approval_handler(
        SimpleNamespace(chat=SimpleNamespace(id=777), text=REJECT_REMINDER_BUTTON_TEXT)
    )

    assert rejected == [42]
    assert bot.sent_messages[-1]["text"] == "❌ Публикация отменена."


from app.telegram import BACK_BUTTON_TEXT, CANCEL_BUTTON_TEXT, MENU_BUTTON_TEXT


def _keyboard_texts(reply_markup) -> list[str]:
    payload = json.loads(reply_markup.to_json())
    return [button["text"] for row in payload["keyboard"] for button in row]


def test_dialog_keyboards_show_back_button_instead_of_cancel() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    keyboards = [
        publisher._manual_post_approval_keyboard(),
        publisher._content_plan_view_keyboard(),
        publisher._content_plan_approval_keyboard(),
        publisher._content_plan_description_keyboard(),
        publisher._reminder_approval_keyboard(),
        publisher._reminders_settings_keyboard(),
        publisher._reminders_custom_keyboard(),
    ]

    for keyboard in keyboards:
        texts = _keyboard_texts(keyboard)
        assert BACK_BUTTON_TEXT in texts
        assert CANCEL_BUTTON_TEXT not in texts


def test_content_plan_dialog_back_returns_to_description_step() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    calls: list[tuple[str, list[str]]] = []

    def generate(description: str, context: list[str] | None = None) -> ContentPlan:
        calls.append((description, list(context or [])))
        return make_plan()

    publisher.register_content_plan_handler(generate, lambda plan: None)

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, "первый план")
    dispatch_text(bot, 555, BACK_BUTTON_TEXT)
    dispatch_text(bot, 555, "новый план")

    assert calls[0] == ("первый план", [])
    assert calls[1] == ("новый план", [])
    assert "Вернулись на шаг описания" in bot.sent_messages[-3]["text"]


def test_content_plan_dialog_back_returns_main_menu_without_approval() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    approved: list[ContentPlan] = []

    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(), approved.append
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, BACK_BUTTON_TEXT)

    assert approved == []
    assert "Диалог контент-плана закрыт" in bot.sent_messages[-1]["text"]
    assert bot.sent_messages[-1]["reply_markup"] is not None


def test_reminders_dialog_back_returns_main_menu_without_saving() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    configured: list[tuple[int | None, int | str]] = []

    publisher.register_reminders_handler(
        lambda minutes, chat_id: configured.append((minutes, chat_id))
    )

    dispatch_text(bot, 777, REMINDERS_BUTTON_TEXT)
    dispatch_text(bot, 777, BACK_BUTTON_TEXT)

    assert configured == []
    assert publisher.reminder_minutes_before is None
    assert "Настройка напоминаний отменена" in bot.sent_messages[-1]["text"]
    assert bot.sent_messages[-1]["reply_markup"] is not None


def test_publication_approval_back_closes_pending_item_without_callback() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    approved: list[int] = []
    rejected: list[int] = []

    publisher.register_publication_approval_handler(
        approved.append,
        rejected.append,
        lambda item_id: make_plan().items[0],
        lambda item_id: make_plan().items[0],
    )

    publisher.send_publication_reminder(777, 42, make_plan().items[0])
    dispatch_text(bot, 777, BACK_BUTTON_TEXT)
    dispatch_text(bot, 777, APPROVE_REMINDER_BUTTON_TEXT)

    assert approved == []
    assert rejected == []
    assert "Решение по напоминанию закрыто" in bot.sent_messages[-2]["text"]
    assert bot.sent_messages[-1]["text"] == "Нет поста, ожидающего решения."


from app.schemas import News, ManualPublicationDraft
from app.telegram import (
    APPROVE_MANUAL_POST_BUTTON_TEXT,
    REGENERATE_MANUAL_TEXT_BUTTON_TEXT,
    VIEW_CONTENT_PLAN_BUTTON_TEXT,
    CREATE_CONTENT_PLAN_BUTTON_TEXT,
)


def make_manual_draft(text: str = "Черновик") -> ManualPublicationDraft:
    news = News(
        title="Новость",
        source_url="https://example.com/manual-news",
        source_name="Example",
        summary="Summary",
    )
    post = GeneratedPost(
        title="Пост",
        text=text,
        image_prompt="Картинка",
        source_url="https://example.com/manual-news",
    )
    return ManualPublicationDraft(news=news, post=post, image=ImageAsset(data=b"img"))


def test_manual_publication_approval_flow_prepares_regenerates_and_approves() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    approved: list[ManualPublicationDraft] = []
    regenerated: list[ManualPublicationDraft] = []

    publisher.register_manual_publish_handler(
        lambda progress: make_manual_draft(),
        approved.append,
        lambda draft: regenerated.append(make_manual_draft("Новый текст"))
        or regenerated[-1],
        lambda draft: draft,
    )

    chat = SimpleNamespace(chat=SimpleNamespace(id=555))
    bot.handlers[1]["func"](
        SimpleNamespace(chat=chat.chat, text=MANUAL_PUBLISH_BUTTON_TEXT)
    )
    bot.handlers[3]["func"](
        SimpleNamespace(chat=chat.chat, text=REGENERATE_MANUAL_TEXT_BUTTON_TEXT)
    )
    bot.handlers[3]["func"](
        SimpleNamespace(chat=chat.chat, text=APPROVE_MANUAL_POST_BUTTON_TEXT)
    )

    assert "Черновик новости" in bot.sent_photos[0]["caption"]
    assert bot.sent_photos[0]["photo"].getvalue() == b"img"
    assert "Новый текст" in bot.sent_photos[1]["caption"]
    assert approved == [regenerated[-1]]
    assert "опубликован в группе" in bot.sent_messages[-1]["text"]


def test_manual_publication_preview_falls_back_to_text_when_image_send_fails() -> None:
    bot = FakeBot(photo_error=RuntimeError("preview image failed"))
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    publisher.register_manual_publish_handler(
        lambda progress: make_manual_draft(),
        lambda draft: None,
        lambda draft: draft,
        lambda draft: draft,
    )

    bot.handlers[1]["func"](
        SimpleNamespace(chat=SimpleNamespace(id=555), text=MANUAL_PUBLISH_BUTTON_TEXT)
    )

    assert bot.sent_photos == []
    assert "Черновик новости" in bot.sent_messages[-1]["text"]
    assert "Картинка: есть" in bot.sent_messages[-1]["text"]
    assert bot.sent_messages[-1]["reply_markup"] is not None


def test_content_plan_menu_can_view_existing_items_and_start_compose() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    calls: list[tuple[str, list[str]]] = []

    def generate(description: str, context: list[str] | None = None) -> ContentPlan:
        calls.append((description, list(context or [])))
        return make_plan()

    publisher.register_content_plan_handler(
        generate,
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, CREATE_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, "план на неделю")

    assert "Выберите действие" in bot.sent_messages[0]["text"]
    assert "#7" in bot.sent_messages[1]["text"]
    assert calls == [("план на неделю", [])]


from app.telegram import (
    EDIT_CONTENT_PLAN_BUTTON_TEXT,
    DELETE_CONTENT_PLAN_BUTTON_TEXT,
    EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT,
    DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT,
)


def test_content_plan_view_can_delete_existing_item() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    deleted: list[int] = []

    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(),
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
        deleted.append,
        lambda item_id, instruction: make_plan().items[0],
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT)
    dispatch_text(bot, 555, "#7")

    assert deleted == [7]
    assert "Пункт КП #7 удален" in bot.sent_messages[-1]["text"]


def test_content_plan_view_can_edit_existing_item_with_ai_instruction() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    edits: list[tuple[int, str]] = []
    updated = (
        make_plan()
        .items[0]
        .model_copy(update={"title": "Обновленный пост", "text": "Новый текст"})
    )

    def edit(item_id: int, instruction: str) -> ContentPlanItem:
        edits.append((item_id, instruction))
        return updated

    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(),
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
        lambda item_id: None,
        edit,
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT)
    dispatch_text(bot, 555, "7")
    dispatch_text(bot, 555, "сделай текст короче и добавь акцент на пользу")

    assert edits == [(7, "сделай текст короче и добавь акцент на пользу")]
    assert "Пункт КП #7 обновлен через ИИ" in bot.sent_messages[-1]["text"]
    assert "Обновленный пост" in bot.sent_messages[-1]["text"]


def test_content_plan_view_can_delete_whole_plan() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    deleted_plans: list[int] = []

    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(),
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
        lambda item_id: None,
        lambda item_id, instruction: make_plan().items[0],
        lambda: [(3, make_plan())],
        deleted_plans.append,
        lambda plan_id, instruction: make_plan(),
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, DELETE_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, "3")

    assert deleted_plans == [3]
    assert "Контент-план #3 удален" in bot.sent_messages[-1]["text"]


def test_content_plan_view_can_edit_whole_plan_with_ai_instruction() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)
    edited_plans: list[tuple[int, str]] = []
    updated_plan = make_plan().model_copy(update={"title": "Обновленный КП"})

    def edit_plan(plan_id: int, instruction: str) -> ContentPlan:
        edited_plans.append((plan_id, instruction))
        return updated_plan

    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(),
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
        lambda item_id: None,
        lambda item_id, instruction: make_plan().items[0],
        lambda: [(3, make_plan())],
        lambda plan_id: None,
        edit_plan,
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, EDIT_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, "3")
    dispatch_text(bot, 555, "измени весь план на следующую неделю")

    assert edited_plans == [(3, "измени весь план на следующую неделю")]
    assert "Контент-план #3 обновлен через ИИ" in bot.sent_messages[-1]["text"]
    assert "Обновленный КП" in bot.sent_messages[-1]["text"]


def test_back_from_content_plan_delete_is_not_handled_as_manual_approval() -> None:
    bot = FakeBot()
    publisher = TelegramPublisher(settings=make_settings(), bot=bot)

    publisher.register_manual_publish_handler(
        lambda progress: make_manual_draft(),
        lambda draft: None,
        lambda draft: draft,
        lambda draft: draft,
    )
    publisher.register_content_plan_handler(
        lambda description, context=None: make_plan(),
        lambda plan: None,
        lambda: [(7, make_plan().items[0])],
        lambda item_id: None,
        lambda item_id, instruction: make_plan().items[0],
        lambda: [(3, make_plan())],
        lambda plan_id: None,
        lambda plan_id, instruction: make_plan(),
    )

    dispatch_text(bot, 555, CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, VIEW_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, DELETE_CONTENT_PLAN_BUTTON_TEXT)
    dispatch_text(bot, 555, BACK_BUTTON_TEXT)

    assert bot.sent_messages[-1]["text"] == "Вернулись в меню контент-плана. Выберите действие."
    assert bot.sent_messages[-1]["reply_markup"] is not None
    assert all(
        message["text"] != "Нет новости, ожидающей согласования."
        for message in bot.sent_messages
    )
