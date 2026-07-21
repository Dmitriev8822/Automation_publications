"""Telegram publishing adapter based on pyTelegramBotAPI."""

from __future__ import annotations

import logging
import urllib.request
from contextlib import nullcontext
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import telebot
from telebot.apihelper import ApiTelegramException
from telebot import types

from app.config import Settings, get_settings
from app.schemas import (
    ContentPlan,
    ContentPlanItem,
    GeneratedPost,
    ImageAsset,
    ManualPublicationDraft,
)

MANUAL_PUBLISH_BUTTON_TEXT = "📰 Опубликовать новость"
CONTENT_PLAN_BUTTON_TEXT = "🗓️ Контент план"
REMINDERS_BUTTON_TEXT = "⏰ Напоминания"
VIEW_CONTENT_PLAN_BUTTON_TEXT = "👀 Посмотреть КП"
CREATE_CONTENT_PLAN_BUTTON_TEXT = "📝 Составить КП"
EDIT_CONTENT_PLAN_BUTTON_TEXT = "✏️ Отредактировать план"
DELETE_CONTENT_PLAN_BUTTON_TEXT = "🗑️ Удалить план"
EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT = "✏️ Отредактировать пункт"
DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT = "🗑️ Удалить пункт"
APPROVE_MANUAL_POST_BUTTON_TEXT = "✅ Принять"
REJECT_MANUAL_POST_BUTTON_TEXT = "❌ Отменить"
REGENERATE_MANUAL_TEXT_BUTTON_TEXT = "✍️ Перегенерировать текст и изображение"
REGENERATE_MANUAL_IMAGE_BUTTON_TEXT = "🖼️ Перегенерировать картинку"
BACK_BUTTON_TEXT = "⬅️ Назад"
MENU_BUTTON_TEXT = "🏠 Меню"
CANCEL_BUTTON_TEXT = "❌ Отмена"
REGENERATE_CONTENT_PLAN_BUTTON_TEXT = "🔄 Перегенерировать"
APPROVE_CONTENT_PLAN_BUTTON_TEXT = "✅ Согласовать"
APPROVE_REMINDER_BUTTON_TEXT = "✅ Одобрить пост"
REJECT_REMINDER_BUTTON_TEXT = "❌ Не выкладывать"
REGENERATE_REMINDER_TEXT_BUTTON_TEXT = "✍️ Перегенерировать текст и изображение"
REGENERATE_REMINDER_IMAGE_BUTTON_TEXT = "🖼️ Перегенерировать картинку"
REMINDER_5_MINUTES_BUTTON_TEXT = "За 5 минут"
REMINDER_15_MINUTES_BUTTON_TEXT = "За 15 минут"
REMINDER_30_MINUTES_BUTTON_TEXT = "За 30 минут"
REMINDER_1_HOUR_BUTTON_TEXT = "За 1 час"
REMINDER_CUSTOM_BUTTON_TEXT = "другое"
TELEGRAM_UNAUTHORIZED_CODE = 401
TELEGRAM_PHOTO_CAPTION_MAX_LENGTH = 1024

REMINDER_PRESET_MINUTES = {
    REMINDER_5_MINUTES_BUTTON_TEXT.lower(): 5,
    REMINDER_15_MINUTES_BUTTON_TEXT.lower(): 15,
    REMINDER_30_MINUTES_BUTTON_TEXT.lower(): 30,
    REMINDER_1_HOUR_BUTTON_TEXT.lower(): 60,
}

MAIN_MENU_BUTTON_TEXTS = {
    MANUAL_PUBLISH_BUTTON_TEXT,
    CONTENT_PLAN_BUTTON_TEXT,
}

MANUAL_POST_APPROVAL_BUTTON_TEXTS = {
    APPROVE_MANUAL_POST_BUTTON_TEXT,
    REJECT_MANUAL_POST_BUTTON_TEXT,
    REGENERATE_MANUAL_TEXT_BUTTON_TEXT,
    REGENERATE_MANUAL_IMAGE_BUTTON_TEXT,
    MENU_BUTTON_TEXT,
    CANCEL_BUTTON_TEXT,
    BACK_BUTTON_TEXT,
}

CONTENT_PLAN_DIALOG_BUTTON_TEXTS = {
    VIEW_CONTENT_PLAN_BUTTON_TEXT,
    CREATE_CONTENT_PLAN_BUTTON_TEXT,
    EDIT_CONTENT_PLAN_BUTTON_TEXT,
    DELETE_CONTENT_PLAN_BUTTON_TEXT,
    EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT,
    DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT,
    REMINDERS_BUTTON_TEXT,
    REGENERATE_CONTENT_PLAN_BUTTON_TEXT,
    APPROVE_CONTENT_PLAN_BUTTON_TEXT,
    BACK_BUTTON_TEXT,
    MENU_BUTTON_TEXT,
    CANCEL_BUTTON_TEXT,
}

REMINDER_APPROVAL_BUTTON_TEXTS = {
    APPROVE_REMINDER_BUTTON_TEXT,
    REJECT_REMINDER_BUTTON_TEXT,
    REGENERATE_REMINDER_TEXT_BUTTON_TEXT,
    REGENERATE_REMINDER_IMAGE_BUTTON_TEXT,
    MENU_BUTTON_TEXT,
    CANCEL_BUTTON_TEXT,
    BACK_BUTTON_TEXT,
}

logger = logging.getLogger(__name__)

START_INSTRUCTION_TEXT = (
    "Готов публиковать новости и работать с контент-планом.\n\n"
    "Как пользоваться ботом:\n"
    f"• {MANUAL_PUBLISH_BUTTON_TEXT} — подготовить новость, посмотреть черновик, "
    "принять, отменить, перегенерировать текст и изображение или отдельно картинку.\n"
    f"• {CONTENT_PLAN_BUTTON_TEXT} — посмотреть запланированные публикации, "
    "составить новый контент-план или настроить напоминания.\n"
    "• /menu — вернуться к этому меню в любой момент."
)

LEGACY_START_INSTRUCTION_TEXT = (
    "Готов публиковать новости.\n\n"
    "Как пользоваться ботом:\n"
    f"• Нажмите {MANUAL_PUBLISH_BUTTON_TEXT}, чтобы запустить ручную публикацию.\n"
    "• /menu — показать меню команд, если оно доступно в вашем клиенте Telegram."
)


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

    def get_me(self) -> Any:
        """Return information about the configured bot token."""

    def set_my_commands(self, commands: list[Any]) -> Any:
        """Configure quick bot commands shown by Telegram clients."""


class TelegramPublisher:
    """Publish generated posts and optional images to a Telegram channel."""

    def __init__(
        self,
        settings: Settings | None = None,
        bot: TelegramBotProtocol | None = None,
        image_url_fetcher: Callable[[str], tuple[bytes, str | None]] | None = None,
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
        self._image_url_fetcher = image_url_fetcher or self._fetch_image_url
        self._content_plan_dialogs: dict[int | str, dict[str, Any]] = {}
        self._manual_post_dialogs: dict[int | str, ManualPublicationDraft] = {}
        self._reminder_dialogs: dict[int | str, dict[str, Any]] = {}
        self.reminder_minutes_before: int | None = None
        self.reminder_chat_id: int | str | None = None
        self._pending_reminder_items: dict[int | str, int] = {}
        logger.info(
            "TelegramPublisher initialized: channel_id=%s bot_injected=%s",
            self.channel_id,
            bot is not None,
        )

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        """Publish a generated post with an optional image and return Telegram message id."""

        logger.info(
            "Publishing Telegram post: source_url=%s has_image=%s",
            post.source_url,
            image is not None,
        )
        try:
            if image is None:
                message = self.bot.send_message(chat_id=self.channel_id, text=post.text)
            else:
                try:
                    photo_context = self._photo_payload(image)
                    with photo_context as photo:
                        message = self._send_photo_post(post.text, photo)
                except Exception as exc:
                    if not self._is_image_process_failed(exc):
                        raise
                    logger.warning(
                        "Telegram rejected generated image for source_url=%s; publishing text-only fallback",
                        post.source_url,
                    )
                    message = self.bot.send_message(
                        chat_id=self.channel_id, text=post.text
                    )
        except Exception as exc:
            raise RuntimeError(f"Telegram publication failed: {exc}") from exc

        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, int):
            raise RuntimeError(
                "Telegram publication failed: response does not contain message_id"
            )
        logger.info("Telegram post published successfully: message_id=%s", message_id)
        return message_id

    def register_manual_publish_handler(
        self,
        prepare_callback: Callable[
            [Callable[[str], None]], ManualPublicationDraft | None
        ],
        approve_callback: Callable[[ManualPublicationDraft], Any] | None = None,
        regenerate_text_callback: (
            Callable[[ManualPublicationDraft], ManualPublicationDraft] | None
        ) = None,
        regenerate_image_callback: (
            Callable[[ManualPublicationDraft], ManualPublicationDraft] | None
        ) = None,
    ) -> None:
        """Register /start, /menu and manual publication approval flow."""

        logger.info("Registering Telegram manual publication handlers")
        self._set_quick_commands()

        if approve_callback is None:

            @self.bot.message_handler(commands=["start"])
            def handle_start(message: Any) -> None:
                self._send_control_message(
                    self._message_chat_id(message),
                    LEGACY_START_INSTRUCTION_TEXT,
                    reply_markup=self._manual_publish_keyboard(),
                )

            @self.bot.message_handler(
                func=lambda message: getattr(message, "text", None)
                == MANUAL_PUBLISH_BUTTON_TEXT
            )
            def handle_manual_publish(message: Any) -> None:
                chat_id = self._message_chat_id(message)

                def progress(message_text: str) -> None:
                    self._send_control_message(chat_id, message_text)

                self._send_control_message(
                    chat_id, "🚀 Запускаю ручную публикацию новости..."
                )
                try:
                    result = prepare_callback(progress)
                except Exception as exc:
                    self._send_control_message(
                        chat_id, f"❌ Публикация завершилась ошибкой: {exc}"
                    )
                    return

                if result is None:
                    self._send_control_message(
                        chat_id, "ℹ️ Публикация не выполнена: нет новых новостей."
                    )
                else:
                    self._send_control_message(
                        chat_id, "🎉 Ручная публикация успешно завершена."
                    )

            return

        @self.bot.message_handler(commands=["start"])
        def handle_start(message: Any) -> None:
            self._send_main_menu(
                self._message_chat_id(message),
                START_INSTRUCTION_TEXT,
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == MANUAL_PUBLISH_BUTTON_TEXT
        )
        def handle_manual_publish(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs.pop(chat_key, None)
            self._reminder_dialogs.pop(chat_key, None)

            def progress(message_text: str) -> None:
                self._send_control_message(chat_id, message_text)

            self._send_control_message(chat_id, "🚀 Готовлю черновик новости...")
            try:
                draft = prepare_callback(progress)
            except Exception as exc:
                self._send_control_message(
                    chat_id, f"❌ Подготовка новости завершилась ошибкой: {exc}"
                )
                return

            if draft is None:
                self._send_control_message(
                    chat_id,
                    "ℹ️ Публикация не выполнена: нет новых новостей.",
                    reply_markup=self._manual_publish_keyboard(),
                )
                return

            if approve_callback is None:
                self._send_control_message(
                    chat_id, "🎉 Ручная публикация успешно завершена."
                )
                return

            self._manual_post_dialogs[chat_key] = draft
            self._send_manual_post_draft(chat_id, draft)

        @self.bot.message_handler(commands=["menu"])
        def handle_menu(message: Any) -> None:
            self._send_main_menu(self._message_chat_id(message), "Главное меню")

        @self.bot.message_handler(
            func=lambda message: self._is_manual_post_approval_message(message)
        )
        def handle_manual_post_approval(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            draft = self._manual_post_dialogs.get(chat_key)
            if draft is None:
                self._send_control_message(
                    chat_id, "Нет новости, ожидающей согласования."
                )
                return
            text = self._message_text(message)
            try:
                if text == APPROVE_MANUAL_POST_BUTTON_TEXT:
                    if approve_callback is None:
                        raise RuntimeError("Approve callback is not configured")
                    approve_callback(draft)
                    self._manual_post_dialogs.pop(chat_key, None)
                    self._send_control_message(
                        chat_id,
                        "✅ Пост принят, опубликован в группе и сохранен в БД.",
                        reply_markup=self._manual_publish_keyboard(),
                    )
                elif text in {
                    REJECT_MANUAL_POST_BUTTON_TEXT,
                    MENU_BUTTON_TEXT,
                    CANCEL_BUTTON_TEXT,
                    BACK_BUTTON_TEXT,
                }:
                    self._manual_post_dialogs.pop(chat_key, None)
                    self._send_main_menu(chat_id, "❌ Публикация новости отменена.")
                elif text == REGENERATE_MANUAL_TEXT_BUTTON_TEXT:
                    if regenerate_text_callback is None:
                        raise RuntimeError(
                            "Text regeneration callback is not configured"
                        )
                    draft = regenerate_text_callback(draft)
                    self._manual_post_dialogs[chat_key] = draft
                    self._send_manual_post_draft(chat_id, draft)
                elif text == REGENERATE_MANUAL_IMAGE_BUTTON_TEXT:
                    if regenerate_image_callback is None:
                        raise RuntimeError(
                            "Image regeneration callback is not configured"
                        )
                    draft = regenerate_image_callback(draft)
                    self._manual_post_dialogs[chat_key] = draft
                    self._send_manual_post_draft(chat_id, draft)
            except Exception as exc:
                self._send_control_message(
                    chat_id, f"❌ Не удалось выполнить действие: {exc}"
                )

    def register_content_plan_handler(
        self,
        generate_callback: Callable[[str], ContentPlan],
        approve_callback: Callable[[ContentPlan], Any],
        list_callback: Callable[[], list[tuple[int, ContentPlanItem]]] | None = None,
        delete_callback: Callable[[int], Any] | None = None,
        edit_callback: Callable[[int, str], ContentPlanItem] | None = None,
        plan_list_callback: Callable[[], list[tuple[int, ContentPlan]]] | None = None,
        delete_plan_callback: Callable[[int], Any] | None = None,
        edit_plan_callback: Callable[[int, str], ContentPlan] | None = None,
    ) -> None:
        """Register a Telegram dialog for generating and approving content plans."""

        if list_callback is None:

            @self.bot.message_handler(
                func=lambda message: getattr(message, "text", None)
                == CONTENT_PLAN_BUTTON_TEXT
            )
            def handle_content_plan_start(message: Any) -> None:
                chat_id = self._message_chat_id(message)
                chat_key = self._chat_key(chat_id)
                self._reminder_dialogs.pop(chat_key, None)
                self._content_plan_dialogs[chat_key] = {"awaiting_description": True}
                self._send_control_message(
                    chat_id,
                    "Опишите контент план в свободном формате: период, темы и желаемое расписание.",
                    reply_markup=self._content_plan_description_keyboard(),
                )

            @self.bot.message_handler(
                func=lambda message: self._is_content_plan_dialog_message(message)
            )
            def handle_content_plan_dialog(message: Any) -> None:
                self._handle_content_plan_dialog_message(
                    message, generate_callback, approve_callback
                )

            return

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._manual_post_dialogs.pop(chat_key, None)
            self._reminder_dialogs.pop(chat_key, None)
            self._content_plan_dialogs.pop(chat_key, None)
            if list_callback is None:
                self._content_plan_dialogs[chat_key] = {"awaiting_description": True}
                self._send_control_message(
                    chat_id,
                    "Опишите контент план в свободном формате: период, темы и желаемое расписание.",
                    reply_markup=self._content_plan_description_keyboard(),
                )
                return
            self._send_control_message(
                chat_id,
                "Выберите действие с контент-планом.",
                reply_markup=self._content_plan_menu_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == VIEW_CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_view(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            if list_callback is None:
                self._send_control_message(
                    chat_id, "Просмотр контент-плана не настроен."
                )
                return
            self._send_control_message(
                chat_id,
                self._format_content_plan_overview(
                    list_callback(),
                    plan_list_callback() if plan_list_callback is not None else [],
                ),
                reply_markup=self._content_plan_view_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT
        )
        def handle_content_plan_delete_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs[chat_key] = {"awaiting_delete_item_id": True}
            self._send_control_message(
                chat_id,
                "Напишите номер пункта КП, который нужно удалить, например 7.",
                reply_markup=self._content_plan_description_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT
        )
        def handle_content_plan_edit_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs[chat_key] = {"awaiting_edit_item_id": True}
            self._send_control_message(
                chat_id,
                "Напишите номер пункта КП для редактирования, например 7.",
                reply_markup=self._content_plan_description_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == DELETE_CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_delete_whole_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs[chat_key] = {"awaiting_delete_plan_id": True}
            self._send_control_message(
                chat_id,
                "Напишите номер всего КП, который нужно удалить, например КП #3.",
                reply_markup=self._content_plan_description_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == EDIT_CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_edit_whole_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs[chat_key] = {"awaiting_edit_plan_id": True}
            self._send_control_message(
                chat_id,
                "Напишите номер всего КП для редактирования, например КП #3.",
                reply_markup=self._content_plan_description_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == CREATE_CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_compose(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs[chat_key] = {"awaiting_description": True}
            self._send_control_message(
                chat_id,
                "Опишите контент план в свободном формате: период, темы и желаемое расписание.",
                reply_markup=self._content_plan_description_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: self._is_content_plan_dialog_message(message)
        )
        def handle_content_plan_dialog(message: Any) -> None:
            self._handle_content_plan_dialog_message(
                message,
                generate_callback,
                approve_callback,
                delete_callback,
                edit_callback,
                delete_plan_callback,
                edit_plan_callback,
            )

    def _handle_content_plan_dialog_message(
        self,
        message: Any,
        generate_callback: Callable[[str], ContentPlan],
        approve_callback: Callable[[ContentPlan], Any],
        delete_callback: Callable[[int], Any] | None = None,
        edit_callback: Callable[[int, str], ContentPlanItem] | None = None,
        delete_plan_callback: Callable[[int], Any] | None = None,
        edit_plan_callback: Callable[[int, str], ContentPlan] | None = None,
    ) -> None:
        chat_id = self._message_chat_id(message)
        chat_key = self._chat_key(chat_id)
        state = self._content_plan_dialogs.get(chat_key, {})
        text = getattr(message, "text", "") or ""

        if text in {MENU_BUTTON_TEXT, CANCEL_BUTTON_TEXT}:
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_main_menu(
                chat_id,
                "Диалог контент-плана отменен. Выберите действие в меню.",
            )
            return

        if text == BACK_BUTTON_TEXT:
            if state.get("awaiting_description") and state.get("plan") is None:
                self._content_plan_dialogs.pop(chat_key, None)
                self._send_main_menu(
                    chat_id,
                    "Диалог контент-плана закрыт. Выберите действие в меню.",
                )
                return
            if self._is_content_plan_management_state(state):
                self._content_plan_dialogs.pop(chat_key, None)
                self._send_control_message(
                    chat_id,
                    "Вернулись в меню контент-плана. Выберите действие.",
                    reply_markup=self._content_plan_menu_keyboard(),
                )
                return
            state.clear()
            state["awaiting_description"] = True
            self._send_control_message(
                chat_id,
                "Вернулись на шаг описания. Отправьте новый контент-план в свободном формате или нажмите «Назад».",
                reply_markup=self._content_plan_description_keyboard(),
            )
            return

        if state.get("awaiting_delete_plan_id"):
            plan_id = self._parse_content_plan_item_id(text)
            if plan_id is None:
                self._send_control_message(
                    chat_id, "Напишите числовой id КП, например 3."
                )
                return
            if delete_plan_callback is None:
                self._send_control_message(
                    chat_id, "Удаление всего контент-плана не настроено."
                )
                return
            delete_plan_callback(plan_id)
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_control_message(
                chat_id,
                f"🗑️ Контент-план #{plan_id} удален.",
                reply_markup=self._manual_publish_keyboard(),
            )
            return

        if state.get("awaiting_edit_plan_id"):
            plan_id = self._parse_content_plan_item_id(text)
            if plan_id is None:
                self._send_control_message(
                    chat_id, "Напишите числовой id КП, например 3."
                )
                return
            state.clear()
            state["awaiting_edit_plan_instruction"] = True
            state["edit_plan_id"] = plan_id
            self._send_control_message(
                chat_id,
                "Напишите, что изменить во всем КП. ИИ перестроит план целиком.",
            )
            return

        if state.get("awaiting_edit_plan_instruction"):
            if edit_plan_callback is None:
                self._send_control_message(
                    chat_id, "Редактирование всего контент-плана не настроено."
                )
                return
            plan_id = int(state["edit_plan_id"])
            updated_plan = edit_plan_callback(plan_id, text)
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_control_message(
                chat_id,
                f"✏️ Контент-план #{plan_id} обновлен через ИИ.\n\n{self._format_content_plan(updated_plan)}",
                reply_markup=self._manual_publish_keyboard(),
            )
            return

        if state.get("awaiting_delete_item_id"):
            item_id = self._parse_content_plan_item_id(text)
            if item_id is None:
                self._send_control_message(
                    chat_id, "Напишите числовой id пункта КП, например 7."
                )
                return
            if delete_callback is None:
                self._send_control_message(
                    chat_id, "Удаление контент-плана не настроено."
                )
                return
            delete_callback(item_id)
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_control_message(
                chat_id,
                f"🗑️ Пункт КП #{item_id} удален.",
                reply_markup=self._manual_publish_keyboard(),
            )
            return

        if state.get("awaiting_edit_item_id"):
            item_id = self._parse_content_plan_item_id(text)
            if item_id is None:
                self._send_control_message(
                    chat_id, "Напишите числовой id пункта КП, например 7."
                )
                return
            state.clear()
            state["awaiting_edit_instruction"] = True
            state["edit_item_id"] = item_id
            self._send_control_message(
                chat_id,
                "Напишите, что изменить. ИИ применит правки к выбранному пункту КП.",
            )
            return

        if state.get("awaiting_edit_instruction"):
            if edit_callback is None:
                self._send_control_message(
                    chat_id, "Редактирование контент-плана не настроено."
                )
                return
            item_id = int(state["edit_item_id"])
            updated_item = edit_callback(item_id, text)
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_control_message(
                chat_id,
                f"✏️ Пункт КП #{item_id} обновлен через ИИ.\n\n{self._format_content_plan_items([(item_id, updated_item)])}",
                reply_markup=self._manual_publish_keyboard(),
            )
            return

        if state.get("awaiting_description"):
            state["description"] = text
            state["awaiting_description"] = False
            self._generate_and_send_content_plan(chat_id, state, generate_callback)
            return

        if text == REGENERATE_CONTENT_PLAN_BUTTON_TEXT:
            self._generate_and_send_content_plan(chat_id, state, generate_callback)
            return

        if text == APPROVE_CONTENT_PLAN_BUTTON_TEXT:
            plan = state.get("plan")
            if not isinstance(plan, ContentPlan):
                self._send_control_message(
                    chat_id, "Сначала нужно сгенерировать контент план."
                )
                return
            approve_callback(plan)
            self._content_plan_dialogs.pop(chat_key, None)
            self._send_control_message(
                chat_id,
                "✅ Контент план согласован и сохранен. Посты будут опубликованы по расписанию.",
                reply_markup=self._manual_publish_keyboard(),
            )
            return

        state.setdefault("dialog_context", []).append(f"Пользователь: {text}")
        self._generate_and_send_content_plan(chat_id, state, generate_callback)

    def _is_manual_post_approval_message(self, message: Any) -> bool:
        text = self._message_text(message)
        if text not in MANUAL_POST_APPROVAL_BUTTON_TEXTS:
            return False
        return self._message_chat_key(message) in self._manual_post_dialogs

    def _is_content_plan_dialog_message(self, message: Any) -> bool:
        text = self._message_text(message)
        if text in MAIN_MENU_BUTTON_TEXTS or text == REMINDERS_BUTTON_TEXT:
            return False
        chat_key = self._message_chat_key(message)
        return chat_key in self._content_plan_dialogs

    @staticmethod
    def _is_content_plan_management_state(state: dict[str, Any]) -> bool:
        return any(
            state.get(key)
            for key in (
                "awaiting_delete_plan_id",
                "awaiting_edit_plan_id",
                "awaiting_edit_plan_instruction",
                "awaiting_delete_item_id",
                "awaiting_edit_item_id",
                "awaiting_edit_instruction",
            )
        )

    def _generate_and_send_content_plan(
        self,
        chat_id: int | str,
        state: dict[str, Any],
        generate_callback: Callable[[str], ContentPlan],
    ) -> None:
        description = str(state.get("description", ""))
        dialog_context = list(state.get("dialog_context", []))
        self._send_control_message(
            chat_id, "🧠 Формирую структурированный контент план..."
        )
        try:
            plan = self._call_content_plan_generator(
                generate_callback, description, dialog_context
            )
        except Exception as exc:
            logger.exception("Content plan generation failed for chat_id=%s", chat_id)
            self._send_control_message(
                chat_id,
                "❌ Не удалось сформировать контент план. "
                f"Проверьте настройки AI/OpenRouter и попробуйте еще раз. Ошибка: {exc}",
                reply_markup=self._manual_publish_keyboard(),
            )
            return
        state.setdefault("dialog_context", []).append(
            f"ИИ предложил план: {plan.title} ({len(plan.items)} постов)"
        )
        state["plan"] = plan
        self._send_control_message(
            chat_id,
            self._format_content_plan(plan),
            reply_markup=self._content_plan_approval_keyboard(),
        )

    @staticmethod
    def _call_content_plan_generator(
        generate_callback: Callable[..., ContentPlan],
        description: str,
        dialog_context: list[str],
    ) -> ContentPlan:
        try:
            return generate_callback(description, dialog_context)
        except TypeError:
            return generate_callback(description)

    def register_reminders_handler(
        self,
        reminder_minutes_callback: Callable[[int | None, int | str], Any] | None = None,
    ) -> None:
        """Register dialog that enables or disables persistent publication reminders."""

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None) == REMINDERS_BUTTON_TEXT
        )
        def handle_reminders_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            self._content_plan_dialogs.pop(chat_key, None)
            self._reminder_dialogs[chat_key] = {"awaiting_minutes": True}
            self._send_control_message(
                chat_id,
                self._format_reminder_settings_prompt(),
                reply_markup=self._reminders_settings_keyboard(),
            )

        @self.bot.message_handler(
            func=lambda message: self._is_reminder_dialog_message(message)
        )
        def handle_reminders_dialog(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            text = (getattr(message, "text", "") or "").strip()
            if text in {MENU_BUTTON_TEXT, CANCEL_BUTTON_TEXT, BACK_BUTTON_TEXT}:
                self._reminder_dialogs.pop(self._chat_key(chat_id), None)
                self._send_main_menu(
                    chat_id,
                    "Настройка напоминаний отменена. Выберите действие в меню.",
                )
                return
            if text.lower() in {"0", "нет", "отключить", "выключить", "off"}:
                self.reminder_minutes_before = None
                self.reminder_chat_id = chat_id
                self._reminder_dialogs.pop(self._chat_key(chat_id), None)
                if reminder_minutes_callback is not None:
                    reminder_minutes_callback(None, chat_id)
                self._send_control_message(
                    chat_id,
                    "✅ Напоминания отключены. Уведомления перед публикациями приходить не будут.",
                    reply_markup=self._manual_publish_keyboard(),
                )
                return
            if text.lower() == "другое":
                self._reminder_dialogs[self._chat_key(chat_id)] = {
                    "awaiting_custom_minutes": True
                }
                self._send_control_message(
                    chat_id,
                    "Напишите свое время в минутах положительным числом, например 45.",
                    reply_markup=self._reminders_custom_keyboard(),
                )
                return
            minutes = self._parse_reminder_minutes(text)
            if minutes is None:
                self._send_control_message(
                    chat_id,
                    "Выберите готовый вариант или напишите положительное число минут, например 45.",
                    reply_markup=self._reminders_settings_keyboard(),
                )
                return
            self.reminder_minutes_before = minutes
            self.reminder_chat_id = chat_id
            self._reminder_dialogs.pop(self._chat_key(chat_id), None)
            if reminder_minutes_callback is not None:
                reminder_minutes_callback(minutes, chat_id)
            self._send_control_message(
                chat_id,
                f"✅ Напомню за {minutes} минут до каждой публикации поста.",
                reply_markup=self._manual_publish_keyboard(),
            )

    def _is_reminder_dialog_message(self, message: Any) -> bool:
        text = self._message_text(message)
        if text in {MENU_BUTTON_TEXT, CANCEL_BUTTON_TEXT, BACK_BUTTON_TEXT}:
            return self._message_chat_key(message) in self._reminder_dialogs
        if text in MAIN_MENU_BUTTON_TEXTS or text in CONTENT_PLAN_DIALOG_BUTTON_TEXTS:
            return False
        return self._message_chat_key(message) in self._reminder_dialogs

    def _format_reminder_settings_prompt(self) -> str:
        if self.reminder_minutes_before is None:
            current = "сейчас напоминания отключены"
        else:
            current = f"сейчас стоит таймер за {self.reminder_minutes_before} минут"
        return (
            f"⏰ {current} до публикации.\n\n"
            "Хотите переустановить таймер? Выберите готовый вариант или нажмите "
            "«другое», чтобы написать свое время в минутах."
        )

    @staticmethod
    def _parse_reminder_minutes(text: str) -> int | None:
        normalized = text.strip().lower()
        if normalized in REMINDER_PRESET_MINUTES:
            return REMINDER_PRESET_MINUTES[normalized]
        try:
            minutes = int(normalized)
        except ValueError:
            return None
        if minutes <= 0:
            return None
        return minutes

    def send_publication_reminder(
        self,
        chat_id: int | str,
        item_id: int,
        item: ContentPlanItem,
        image: ImageAsset | None = None,
    ) -> int:
        """Send pre-publication approval controls for a scheduled post."""

        self._pending_reminder_items[self._chat_key(chat_id)] = item_id
        text = f"⏰ Скоро публикация #{item_id}: {item.title}\n\n{item.text}\n\nКартинка: {item.image_prompt or 'без описания'}"
        reply_markup = self._reminder_approval_keyboard()
        if image is None:
            return self._send_control_message(chat_id, text, reply_markup=reply_markup)

        try:
            return self._send_control_photo(
                chat_id, image, text, reply_markup=reply_markup
            )
        except Exception:
            logger.warning(
                "Could not send content-plan reminder image preview to chat_id=%s item_id=%s; sending text-only preview",
                chat_id,
                item_id,
                exc_info=True,
            )
            return self._send_control_message(chat_id, text, reply_markup=reply_markup)

    @staticmethod
    def _reminder_approval_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(APPROVE_REMINDER_BUTTON_TEXT),
            types.KeyboardButton(REJECT_REMINDER_BUTTON_TEXT),
        )
        keyboard.add(
            types.KeyboardButton(REGENERATE_REMINDER_TEXT_BUTTON_TEXT),
            types.KeyboardButton(REGENERATE_REMINDER_IMAGE_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    def _send_manual_post_draft(
        self, chat_id: int | str, draft: ManualPublicationDraft
    ) -> int:
        image_state = "есть" if draft.image is not None else "нет"
        text = (
            f"📰 Черновик новости: {draft.post.title}\n"
            f"Источник: {draft.post.source_url}\n"
            f"Картинка: {image_state}\n\n"
            f"{draft.post.text}"
        )
        reply_markup = self._manual_post_approval_keyboard()
        if draft.image is None:
            return self._send_control_message(chat_id, text, reply_markup=reply_markup)

        try:
            return self._send_control_photo(
                chat_id, draft.image, text, reply_markup=reply_markup
            )
        except Exception:
            logger.warning(
                "Could not send manual draft image preview to chat_id=%s; sending text-only preview",
                chat_id,
                exc_info=True,
            )
            return self._send_control_message(chat_id, text, reply_markup=reply_markup)

    @staticmethod
    def _manual_post_approval_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(APPROVE_MANUAL_POST_BUTTON_TEXT),
            types.KeyboardButton(REJECT_MANUAL_POST_BUTTON_TEXT),
        )
        keyboard.add(
            types.KeyboardButton(REGENERATE_MANUAL_TEXT_BUTTON_TEXT),
            types.KeyboardButton(REGENERATE_MANUAL_IMAGE_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    @staticmethod
    def _parse_content_plan_item_id(text: str) -> int | None:
        digits = "".join(character for character in text if character.isdigit())
        if not digits:
            return None
        item_id = int(digits)
        return item_id if item_id > 0 else None

    @staticmethod
    def _content_plan_menu_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(VIEW_CONTENT_PLAN_BUTTON_TEXT),
            types.KeyboardButton(CREATE_CONTENT_PLAN_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(REMINDERS_BUTTON_TEXT))
        return keyboard

    @staticmethod
    def _content_plan_view_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(EDIT_CONTENT_PLAN_ITEM_BUTTON_TEXT),
            types.KeyboardButton(DELETE_CONTENT_PLAN_ITEM_BUTTON_TEXT),
        )
        keyboard.add(
            types.KeyboardButton(EDIT_CONTENT_PLAN_BUTTON_TEXT),
            types.KeyboardButton(DELETE_CONTENT_PLAN_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    @classmethod
    def _format_content_plan_overview(
        cls,
        items: list[tuple[int, ContentPlanItem]],
        plans: list[tuple[int, ContentPlan]],
    ) -> str:
        sections: list[str] = []
        if plans:
            lines = ["🗂️ Контент-планы:", ""]
            for plan_id, plan in plans:
                lines.append(f"КП #{plan_id}: {plan.title} ({len(plan.items)} пунктов)")
            sections.append("\n".join(lines))
        sections.append(cls._format_content_plan_items(items))
        return "\n\n".join(sections).strip()

    @staticmethod
    def _format_content_plan_items(items: list[tuple[int, ContentPlanItem]]) -> str:
        if not items:
            return "Контент-план пуст: запланированных публикаций нет."
        lines = ["🗓️ Запланированные публикации:", ""]
        for item_id, item in items:
            lines.append(
                f"#{item_id} {item.scheduled_at.isoformat()} — {item.title} ({item.status.value})"
            )
            lines.append(item.text)
            if item.image_prompt:
                lines.append(f"Картинка: {item.image_prompt}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _format_content_plan(plan: ContentPlan) -> str:
        lines = [
            f"🗓️ {plan.title}",
            f"Период: {plan.period_start.isoformat()} — {plan.period_end.isoformat()}",
            "",
        ]
        for index, item in enumerate(plan.items, start=1):
            lines.append(f"{index}. {item.scheduled_at.isoformat()} — {item.title}")
            lines.append(item.text)
        return "\n".join(lines)

    @staticmethod
    def _content_plan_approval_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(REGENERATE_CONTENT_PLAN_BUTTON_TEXT),
            types.KeyboardButton(APPROVE_CONTENT_PLAN_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    @staticmethod
    def _content_plan_description_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    @staticmethod
    def _reminders_settings_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(REMINDER_5_MINUTES_BUTTON_TEXT),
            types.KeyboardButton(REMINDER_15_MINUTES_BUTTON_TEXT),
        )
        keyboard.add(
            types.KeyboardButton(REMINDER_30_MINUTES_BUTTON_TEXT),
            types.KeyboardButton(REMINDER_1_HOUR_BUTTON_TEXT),
        )
        keyboard.add(
            types.KeyboardButton(REMINDER_CUSTOM_BUTTON_TEXT),
            types.KeyboardButton(BACK_BUTTON_TEXT),
        )
        return keyboard

    @staticmethod
    def _reminders_custom_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton(BACK_BUTTON_TEXT))
        return keyboard

    def register_publication_approval_handler(
        self,
        approve_callback: Callable[[int], Any],
        reject_callback: Callable[[int], Any],
        regenerate_text_callback: Callable[[int], ContentPlanItem],
        regenerate_image_callback: Callable[[int], ContentPlanItem],
    ) -> None:
        """Register controls shown in pre-publication reminders."""

        @self.bot.message_handler(
            func=lambda message: self._is_publication_approval_message(message)
        )
        def handle_publication_approval(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            chat_key = self._chat_key(chat_id)
            item_id = self._pending_reminder_items.get(chat_key)
            if item_id is None:
                self._send_control_message(chat_id, "Нет поста, ожидающего решения.")
                return
            text = getattr(message, "text", None)
            if text in {MENU_BUTTON_TEXT, CANCEL_BUTTON_TEXT, BACK_BUTTON_TEXT}:
                self._pending_reminder_items.pop(chat_key, None)
                self._send_main_menu(
                    chat_id,
                    "Решение по напоминанию закрыто. Запланированный пост не изменен.",
                )
                return
            try:
                if text == APPROVE_REMINDER_BUTTON_TEXT:
                    approve_callback(item_id)
                    self._pending_reminder_items.pop(chat_key, None)
                    self._send_control_message(
                        chat_id,
                        "✅ Пост одобрен и опубликован в канале.",
                        reply_markup=self._manual_publish_keyboard(),
                    )
                elif text == REJECT_REMINDER_BUTTON_TEXT:
                    reject_callback(item_id)
                    self._pending_reminder_items.pop(chat_key, None)
                    self._send_control_message(
                        chat_id,
                        "❌ Публикация отменена.",
                        reply_markup=self._manual_publish_keyboard(),
                    )
                elif text == REGENERATE_REMINDER_TEXT_BUTTON_TEXT:
                    item = regenerate_text_callback(item_id)
                    self.send_publication_reminder(chat_id, item_id, item)
                elif text == REGENERATE_REMINDER_IMAGE_BUTTON_TEXT:
                    item = regenerate_image_callback(item_id)
                    self.send_publication_reminder(chat_id, item_id, item)
            except Exception as exc:
                self._send_control_message(
                    chat_id, f"❌ Не удалось выполнить действие: {exc}"
                )

    def _is_publication_approval_message(self, message: Any) -> bool:
        text = self._message_text(message)
        if text not in REMINDER_APPROVAL_BUTTON_TEXTS:
            return False
        if text in {MENU_BUTTON_TEXT, CANCEL_BUTTON_TEXT, BACK_BUTTON_TEXT}:
            return self._message_chat_key(message) in self._pending_reminder_items
        return True

    def _set_quick_commands(self) -> None:
        """Expose /start and /menu in Telegram quick commands."""

        self.bot.set_my_commands(
            [
                types.BotCommand("start", "Открыть главное меню"),
                types.BotCommand("menu", "Показать меню"),
            ]
        )

    def start_manual_polling(self) -> None:
        """Start polling for manual publication commands."""

        logger.info("Starting Telegram bot infinity polling for manual controls")
        try:
            self.bot.infinity_polling(skip_pending=True)
        except ApiTelegramException as exc:
            self._raise_telegram_api_error("Telegram bot polling failed", exc)

    def validate_bot_token(self) -> str:
        """Validate bot token with Telegram getMe and return a readable bot name."""

        logger.info("Validating Telegram bot token with getMe")
        try:
            bot_info = self.bot.get_me()
        except ApiTelegramException as exc:
            self._raise_telegram_api_error("Telegram bot token check failed", exc)
        except Exception as exc:
            raise RuntimeError(f"Telegram bot token check failed: {exc}") from exc

        username = getattr(bot_info, "username", None)
        first_name = getattr(bot_info, "first_name", None)
        if username:
            return f"@{username}"
        if first_name:
            return str(first_name)
        return "<unknown bot>"

    @staticmethod
    def _require_setting(value: str | None, error_message: str) -> str:
        if not value:
            raise ValueError(error_message)
        return value.strip()

    @classmethod
    def _raise_telegram_api_error(cls, prefix: str, exc: ApiTelegramException) -> None:
        if cls._is_unauthorized_error(exc):
            raise RuntimeError(
                f"{prefix}: Telegram API returned 401 Unauthorized. "
                "Check TELEGRAM_BOT_TOKEN: it must be the exact token issued by @BotFather "
                "in the '<bot_id>:<secret>' format, without quotes or extra spaces. "
                "You can verify it with: python app/main.py --check-telegram"
            ) from exc
        raise RuntimeError(f"{prefix}: {exc}") from exc

    @staticmethod
    def _is_unauthorized_error(exc: ApiTelegramException) -> bool:
        return getattr(exc, "error_code", None) == TELEGRAM_UNAUTHORIZED_CODE

    @staticmethod
    def _is_image_process_failed(exc: Exception) -> bool:
        if not isinstance(exc, ApiTelegramException):
            return False
        description = str(getattr(exc, "description", "")) or str(exc)
        return (
            getattr(exc, "error_code", None) == 400
            and "IMAGE_PROCESS_FAILED" in description
        )

    def _send_photo_post(self, text: str, photo: Any) -> Any:
        if len(text) <= TELEGRAM_PHOTO_CAPTION_MAX_LENGTH:
            return self.bot.send_photo(
                chat_id=self.channel_id,
                photo=photo,
                caption=text,
            )

        caption = text[: TELEGRAM_PHOTO_CAPTION_MAX_LENGTH - 1].rstrip() + "…"
        photo_message = self.bot.send_photo(
            chat_id=self.channel_id,
            photo=photo,
            caption=caption,
        )
        self.bot.send_message(chat_id=self.channel_id, text=text)
        return photo_message

    def _photo_payload(self, image: ImageAsset):
        if image.data is not None:
            return nullcontext(self._bytes_photo_payload(image.data, image.mime_type))
        if image.file_path is not None:
            return Path(image.file_path).open("rb")
        if image.url is not None:
            image_data, mime_type = self._image_url_fetcher(str(image.url))
            return nullcontext(
                self._bytes_photo_payload(image_data, mime_type or image.mime_type)
            )
        raise ValueError("ImageAsset must contain data, url, or file_path")

    @staticmethod
    def _bytes_photo_payload(image_data: bytes, mime_type: str) -> BytesIO:
        payload = BytesIO(image_data)
        payload.name = (
            f"telegram-image{TelegramPublisher._extension_for_mime_type(mime_type)}"
        )
        return payload

    @staticmethod
    def _fetch_image_url(url: str) -> tuple[bytes, str | None]:
        with urllib.request.urlopen(url, timeout=30) as response:
            content_type = response.headers.get("Content-Type")
            return response.read(), content_type

    @staticmethod
    def _extension_for_mime_type(mime_type: str) -> str:
        normalized = (mime_type or "").split(";", maxsplit=1)[0].strip().lower()
        return {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(normalized, ".jpg")

    @staticmethod
    def _manual_publish_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(MANUAL_PUBLISH_BUTTON_TEXT),
            types.KeyboardButton(CONTENT_PLAN_BUTTON_TEXT),
        )
        return keyboard

    def _send_main_menu(self, chat_id: str | int, text: str) -> int:
        return self._send_control_message(
            chat_id, text, reply_markup=self._manual_publish_keyboard()
        )

    def _send_control_message(
        self, chat_id: str | int, text: str, **kwargs: Any
    ) -> int:
        message = self.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, int):
            raise RuntimeError(
                "Telegram control message failed: response does not contain message_id"
            )
        return message_id

    def _send_control_photo(
        self,
        chat_id: str | int,
        image: ImageAsset,
        caption: str,
        **kwargs: Any,
    ) -> int:
        if len(caption) <= TELEGRAM_PHOTO_CAPTION_MAX_LENGTH:
            with self._photo_payload(image) as photo:
                message = self.bot.send_photo(
                    chat_id=chat_id, photo=photo, caption=caption, **kwargs
                )
            return self._extract_control_message_id(message, "photo preview")

        preview_caption = (
            caption[: TELEGRAM_PHOTO_CAPTION_MAX_LENGTH - 1].rstrip() + "…"
        )
        with self._photo_payload(image) as photo:
            self.bot.send_photo(chat_id=chat_id, photo=photo, caption=preview_caption)
        return self._send_control_message(chat_id, caption, **kwargs)

    @staticmethod
    def _extract_control_message_id(message: Any, action: str) -> int:
        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, int):
            raise RuntimeError(
                f"Telegram control {action} failed: response does not contain message_id"
            )
        return message_id

    @staticmethod
    def _chat_key(chat_id: int | str) -> str:
        """Return a stable key for Telegram chat ids from DB and incoming updates."""

        return str(chat_id)

    def _message_chat_key(self, message: Any) -> str:
        return self._chat_key(self._message_chat_id(message))

    @staticmethod
    def _message_chat_id(message: Any) -> int | str:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            raise RuntimeError("Telegram message does not contain chat.id")
        return chat_id

    @staticmethod
    def _message_text(message: Any) -> str | None:
        return getattr(message, "text", None)
