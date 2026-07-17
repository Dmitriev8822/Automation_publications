"""Telegram publishing adapter based on pyTelegramBotAPI."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import telebot
from telebot.apihelper import ApiTelegramException
from telebot import types

from app.config import Settings, get_settings
from app.schemas import ContentPlan, ContentPlanItem, GeneratedPost, ImageAsset

MANUAL_PUBLISH_BUTTON_TEXT = "📰 Опубликовать новость"
CONTENT_PLAN_BUTTON_TEXT = "🗓️ Контент план"
REMINDERS_BUTTON_TEXT = "⏰ Напоминания"
REGENERATE_CONTENT_PLAN_BUTTON_TEXT = "🔄 Перегенерировать"
APPROVE_CONTENT_PLAN_BUTTON_TEXT = "✅ Согласовать"
APPROVE_REMINDER_BUTTON_TEXT = "✅ Одобрить пост"
REJECT_REMINDER_BUTTON_TEXT = "❌ Не выкладывать"
REGENERATE_REMINDER_TEXT_BUTTON_TEXT = "✍️ Перегенерировать текст"
REGENERATE_REMINDER_IMAGE_BUTTON_TEXT = "🖼️ Перегенерировать картинку"
TELEGRAM_UNAUTHORIZED_CODE = 401

logger = logging.getLogger(__name__)


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
        self._content_plan_dialogs: dict[int | str, dict[str, Any]] = {}
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
                        message = self.bot.send_photo(
                            chat_id=self.channel_id,
                            photo=photo,
                            caption=post.text,
                        )
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
        publish_callback: Callable[[Callable[[str], None]], Any],
    ) -> None:
        """Register /start and button handlers for manual publication from the bot chat."""

        logger.info("Registering Telegram manual publication handlers")

        @self.bot.message_handler(commands=["start"])
        def handle_start(message: Any) -> None:
            self._send_control_message(
                self._message_chat_id(message),
                "Готов публиковать новости. Нажмите кнопку ниже, чтобы запустить публикацию вручную.",
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
                result = publish_callback(progress)
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

    def register_content_plan_handler(
        self,
        generate_callback: Callable[[str], ContentPlan],
        approve_callback: Callable[[ContentPlan], Any],
    ) -> None:
        """Register a Telegram dialog for generating and approving content plans."""

        @self.bot.message_handler(
            func=lambda message: getattr(message, "text", None)
            == CONTENT_PLAN_BUTTON_TEXT
        )
        def handle_content_plan_start(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            self._content_plan_dialogs[chat_id] = {"awaiting_description": True}
            self._send_control_message(
                chat_id,
                "Опишите контент план в свободном формате: период, темы и желаемое расписание.",
            )

        @self.bot.message_handler(
            func=lambda message: self._is_content_plan_dialog_message(message)
        )
        def handle_content_plan_dialog(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            state = self._content_plan_dialogs.get(chat_id, {})
            text = getattr(message, "text", "") or ""

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
                self._content_plan_dialogs.pop(chat_id, None)
                self._send_control_message(
                    chat_id,
                    "✅ Контент план согласован и сохранен. Посты будут опубликованы по расписанию.",
                )
                return

            state.setdefault("dialog_context", []).append(f"Пользователь: {text}")
            self._generate_and_send_content_plan(chat_id, state, generate_callback)

    def _is_content_plan_dialog_message(self, message: Any) -> bool:
        chat_id = self._message_chat_id(message)
        return chat_id in self._content_plan_dialogs

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
            self._reminder_dialogs[chat_id] = {"awaiting_minutes": True}
            self._send_control_message(
                chat_id,
                "За сколько минут до публикации напоминать? Отправьте число минут или 0, чтобы отключить напоминания.",
            )

        @self.bot.message_handler(
            func=lambda message: self._is_reminder_dialog_message(message)
        )
        def handle_reminders_dialog(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            text = (getattr(message, "text", "") or "").strip()
            if text.lower() in {"0", "нет", "отключить", "выключить", "off"}:
                self.reminder_minutes_before = None
                self.reminder_chat_id = chat_id
                self._reminder_dialogs.pop(chat_id, None)
                if reminder_minutes_callback is not None:
                    reminder_minutes_callback(None, chat_id)
                self._send_control_message(
                    chat_id,
                    "✅ Напоминания отключены. Уведомления перед публикациями приходить не будут.",
                )
                return
            try:
                minutes = int(text)
                if minutes <= 0:
                    raise ValueError
            except ValueError:
                self._send_control_message(
                    chat_id,
                    "Введите положительное число минут, например 30, или 0 для отключения.",
                )
                return
            self.reminder_minutes_before = minutes
            self.reminder_chat_id = chat_id
            self._reminder_dialogs.pop(chat_id, None)
            if reminder_minutes_callback is not None:
                reminder_minutes_callback(minutes, chat_id)
            self._send_control_message(
                chat_id, f"✅ Напомню за {minutes} минут до каждой публикации поста."
            )

    def _is_reminder_dialog_message(self, message: Any) -> bool:
        return self._message_chat_id(message) in self._reminder_dialogs

    def send_publication_reminder(
        self,
        chat_id: int | str,
        item_id: int,
        item: ContentPlanItem,
    ) -> int:
        """Send pre-publication approval controls for a scheduled post."""

        self._pending_reminder_items[chat_id] = item_id
        text = f"⏰ Скоро публикация #{item_id}: {item.title}\n\n{item.text}\n\nКартинка: {item.image_prompt or 'без описания'}"
        return self._send_control_message(
            chat_id, text, reply_markup=self._reminder_approval_keyboard()
        )

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
        return keyboard

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
            func=lambda message: getattr(message, "text", None)
            in {
                APPROVE_REMINDER_BUTTON_TEXT,
                REJECT_REMINDER_BUTTON_TEXT,
                REGENERATE_REMINDER_TEXT_BUTTON_TEXT,
                REGENERATE_REMINDER_IMAGE_BUTTON_TEXT,
            }
        )
        def handle_publication_approval(message: Any) -> None:
            chat_id = self._message_chat_id(message)
            item_id = self._pending_reminder_items.get(chat_id)
            if item_id is None:
                self._send_control_message(chat_id, "Нет поста, ожидающего решения.")
                return
            text = getattr(message, "text", None)
            try:
                if text == APPROVE_REMINDER_BUTTON_TEXT:
                    approve_callback(item_id)
                    self._pending_reminder_items.pop(chat_id, None)
                    self._send_control_message(
                        chat_id, "✅ Пост одобрен и опубликован."
                    )
                elif text == REJECT_REMINDER_BUTTON_TEXT:
                    reject_callback(item_id)
                    self._pending_reminder_items.pop(chat_id, None)
                    self._send_control_message(chat_id, "❌ Публикация отменена.")
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

    @staticmethod
    def _photo_payload(image: ImageAsset):
        if image.data is not None:
            payload = BytesIO(image.data)
            payload.name = (
                "telegram-image"  # pyTelegramBotAPI uses it as multipart filename.
            )
            return nullcontext(payload)
        if image.file_path is not None:
            return Path(image.file_path).open("rb")
        if image.url is not None:
            return nullcontext(str(image.url))
        raise ValueError("ImageAsset must contain data, url, or file_path")

    @staticmethod
    def _manual_publish_keyboard() -> types.ReplyKeyboardMarkup:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton(MANUAL_PUBLISH_BUTTON_TEXT),
            types.KeyboardButton(CONTENT_PLAN_BUTTON_TEXT),
        )
        keyboard.add(types.KeyboardButton(REMINDERS_BUTTON_TEXT))
        return keyboard

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

    @staticmethod
    def _message_chat_id(message: Any) -> int | str:
        chat = getattr(message, "chat", None)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            raise RuntimeError("Telegram message does not contain chat.id")
        return chat_id
