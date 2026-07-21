"""Application entry point and dependency wiring."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.ai import AIClient
from app.config import Settings, get_settings, validate_runtime_settings
from app.database import (
    ContentPlanRepository,
    PostRepository,
    ReminderSettingsRepository,
    init_db,
)
from app.scheduler import (
    add_content_plan_item_jobs,
    add_content_plan_reminder_jobs,
    create_content_plan_scheduler,
    remove_content_plan_reminder_jobs,
    create_scheduler,
)
from app.service import (
    approve_content_plan_item_publication,
    create_and_publish_post,
    create_manual_publication_draft,
    publish_due_content_plan_items,
    publish_manual_publication_draft,
    reject_content_plan_publication,
    regenerate_content_plan,
    regenerate_content_plan_item_image,
    regenerate_content_plan_item_text,
    regenerate_manual_publication_image,
    regenerate_manual_publication_text,
    reject_content_plan_item_publication,
)
from app.schemas import (
    ContentPlanItem,
    ContentPlanItemStatus,
    GeneratedPost,
    ImageAsset,
)
from app.telegram import TelegramPublisher

logger = logging.getLogger(__name__)

STARTUP_TEST_ARGS = ("tests", "-q")


@dataclass(frozen=True)
class ApplicationRuntime:
    """Runtime dependencies that need to stay alive while the app runs."""

    scheduler: object
    telegram_publisher: TelegramPublisher


def configure_logging(log_level: str) -> None:
    """Configure root logging for the runnable application."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def run_startup_tests(args: Sequence[str] = STARTUP_TEST_ARGS) -> bool:
    """Run fast startup checks and return whether they passed."""

    logger.info("Running startup tests: pytest %s", " ".join(args))
    root_logger = logging.getLogger()
    previous_handler_levels = [
        (handler, handler.level) for handler in root_logger.handlers
    ]
    for handler, _level in previous_handler_levels:
        handler.setLevel(logging.CRITICAL + 1)
    try:
        exit_code = pytest.main(list(args))
    finally:
        for handler, level in previous_handler_levels:
            handler.setLevel(level)

    if exit_code != pytest.ExitCode.OK:
        logger.error("Startup tests failed with exit code %s", exit_code)
        return False
    logger.info("Startup tests passed")
    return True


def build_scheduler(settings: Settings):
    """Initialize infrastructure and return a configured scheduler."""

    logger.info("Building runtime dependencies")
    validate_runtime_settings(settings)
    init_db()

    logger.info("Creating PostRepository, AIClient and TelegramPublisher")
    repository = PostRepository()
    ai_client = AIClient(settings)
    telegram_publisher = TelegramPublisher(settings)

    job = lambda: create_and_publish_post(ai_client, telegram_publisher, repository)
    return create_scheduler(job, settings.publish_interval_minutes)


def build_runtime(settings: Settings) -> ApplicationRuntime:
    """Initialize infrastructure and register scheduled and manual publication entrypoints."""

    logger.info("Building runtime dependencies")
    validate_runtime_settings(settings)
    init_db()

    logger.info("Creating PostRepository, AIClient and TelegramPublisher")
    repository = PostRepository()
    content_plan_repository = ContentPlanRepository()
    reminder_settings_repository = ReminderSettingsRepository()
    ai_client = AIClient(settings)
    telegram_publisher = TelegramPublisher(settings)

    def scheduled_content_plan_job():
        publish_due_content_plan_items(
            telegram_publisher, content_plan_repository, ai_client
        )

    manual_prepare_job = lambda progress: create_manual_publication_draft(
        ai_client, repository, progress_callback=progress
    )
    try:
        telegram_publisher.register_manual_publish_handler(
            manual_prepare_job,
            lambda draft: publish_manual_publication_draft(
                draft, telegram_publisher, repository
            ),
            lambda draft: regenerate_manual_publication_text(draft, ai_client),
            lambda draft: regenerate_manual_publication_image(draft, ai_client),
        )
    except TypeError:
        logger.warning(
            "Telegram publisher supports only the legacy manual handler signature"
        )
        telegram_publisher.register_manual_publish_handler(manual_prepare_job)

    logger.info("Creating content-plan scheduler from persisted scheduled items")
    scheduler = create_content_plan_scheduler(
        scheduled_content_plan_job,
        content_plan_repository.get_scheduled_item_slots(),
    )

    def schedule_persistent_reminders() -> None:
        enabled, minutes, chat_id = reminder_settings_repository.get_settings()
        remove_content_plan_reminder_jobs(scheduler)
        if not enabled or minutes is None or chat_id is None:
            telegram_publisher.reminder_minutes_before = None
            telegram_publisher.reminder_chat_id = chat_id
            return
        telegram_publisher.reminder_minutes_before = minutes
        telegram_publisher.reminder_chat_id = chat_id
        add_content_plan_reminder_jobs(
            scheduler,
            reminder_job,
            content_plan_repository.get_scheduled_item_slots(),
            minutes,
        )

    def save_content_plan_and_schedule(plan):
        plan_id = content_plan_repository.save_plan(plan)
        add_content_plan_item_jobs(
            scheduler,
            scheduled_content_plan_job,
            content_plan_repository.get_scheduled_item_slots(),
        )
        schedule_persistent_reminders()
        return plan_id

    list_scheduled_items = getattr(
        content_plan_repository, "list_scheduled_items", lambda: []
    )
    list_scheduled_plans = getattr(
        content_plan_repository, "list_scheduled_plans", lambda: []
    )

    def delete_content_plan_item(item_id: int) -> ContentPlanItem:
        item = reject_content_plan_item_publication(
            item_id, content_plan_repository, "User deleted item from content-plan view"
        )
        add_content_plan_item_jobs(
            scheduler,
            scheduled_content_plan_job,
            content_plan_repository.get_scheduled_item_slots(),
        )
        schedule_persistent_reminders()
        return item

    def edit_content_plan_item(item_id: int, instruction: str) -> ContentPlanItem:
        item = regenerate_content_plan_item_text(
            item_id, ai_client, content_plan_repository, instruction
        )
        add_content_plan_item_jobs(
            scheduler,
            scheduled_content_plan_job,
            content_plan_repository.get_scheduled_item_slots(),
        )
        schedule_persistent_reminders()
        return item

    def delete_content_plan(plan_id: int) -> list[ContentPlanItem]:
        items = reject_content_plan_publication(
            plan_id, content_plan_repository, "User deleted whole content plan"
        )
        add_content_plan_item_jobs(
            scheduler,
            scheduled_content_plan_job,
            content_plan_repository.get_scheduled_item_slots(),
        )
        schedule_persistent_reminders()
        return items

    def edit_content_plan(plan_id: int, instruction: str):
        _plan_id, plan = regenerate_content_plan(
            plan_id, ai_client, content_plan_repository, instruction
        )
        add_content_plan_item_jobs(
            scheduler,
            scheduled_content_plan_job,
            content_plan_repository.get_scheduled_item_slots(),
        )
        schedule_persistent_reminders()
        return plan

    try:
        telegram_publisher.register_content_plan_handler(
            ai_client.generate_content_plan,
            save_content_plan_and_schedule,
            list_scheduled_items,
            delete_content_plan_item,
            edit_content_plan_item,
            list_scheduled_plans,
            delete_content_plan,
            edit_content_plan,
        )
    except TypeError:
        logger.warning(
            "Telegram publisher supports only the legacy content-plan handler signature"
        )
        telegram_publisher.register_content_plan_handler(
            ai_client.generate_content_plan, save_content_plan_and_schedule
        )

    def reminder_job(item_id: int):
        if telegram_publisher.reminder_chat_id is None:
            return
        item = content_plan_repository.get_item(item_id)
        if item.status != ContentPlanItemStatus.SCHEDULED:
            logger.info(
                "Skipping reminder for content-plan item with status %s: item_id=%s",
                item.status,
                item_id,
            )
            return
        image = _generate_content_plan_item_preview_image(item_id, item, ai_client)
        telegram_publisher.send_publication_reminder(
            telegram_publisher.reminder_chat_id, item_id, item, image
        )

    def configure_reminders(minutes: int | None, chat_id: int | str):
        if minutes is None:
            reminder_settings_repository.disable()
        else:
            reminder_settings_repository.enable(minutes, chat_id)
        schedule_persistent_reminders()

    if hasattr(telegram_publisher, "register_reminders_handler"):
        schedule_persistent_reminders()
        telegram_publisher.register_reminders_handler(configure_reminders)
    if hasattr(telegram_publisher, "register_publication_approval_handler"):
        telegram_publisher.register_publication_approval_handler(
            lambda item_id: approve_content_plan_item_publication(
                item_id, telegram_publisher, content_plan_repository, ai_client
            ),
            lambda item_id: reject_content_plan_item_publication(
                item_id, content_plan_repository
            ),
            lambda item_id: _regenerate_content_plan_item_text_preview(
                item_id, ai_client, content_plan_repository
            ),
            lambda item_id: _regenerate_content_plan_item_image_preview(
                item_id, ai_client, content_plan_repository
            ),
        )

    logger.info(
        "Content-plan scheduler created with %d job(s)", len(scheduler.get_jobs())
    )
    return ApplicationRuntime(
        scheduler=scheduler, telegram_publisher=telegram_publisher
    )


def _generate_content_plan_item_preview_image(
    item_id: int, item: ContentPlanItem, ai_client: AIClient
) -> ImageAsset | None:
    """Generate an image preview for a scheduled content-plan approval message."""

    if not item.image_prompt:
        return None
    generated_post = GeneratedPost(
        title=item.title,
        text=item.text,
        image_prompt=item.image_prompt,
        source_url=item.source_url or f"https://content-plan.local/items/{item_id}",
    )
    try:
        return ai_client.generate_image(generated_post)
    except Exception:  # noqa: BLE001 - reminder should still be delivered as text
        logger.warning(
            "Could not generate content-plan reminder image preview: item_id=%s",
            item_id,
            exc_info=True,
        )
        return None


def _regenerate_content_plan_item_text_preview(
    item_id: int, ai_client: AIClient, content_plan_repository: ContentPlanRepository
) -> tuple[ContentPlanItem, ImageAsset | None]:
    """Regenerate text and return a fresh image preview for the reminder chat."""

    item = regenerate_content_plan_item_text(
        item_id, ai_client, content_plan_repository
    )
    return item, _generate_content_plan_item_preview_image(item_id, item, ai_client)


def _regenerate_content_plan_item_image_preview(
    item_id: int, ai_client: AIClient, content_plan_repository: ContentPlanRepository
) -> tuple[ContentPlanItem, ImageAsset | None]:
    """Regenerate image prompt and return a fresh image preview for the reminder chat."""

    item = regenerate_content_plan_item_image(
        item_id, ai_client, content_plan_repository
    )
    return item, _generate_content_plan_item_preview_image(item_id, item, ai_client)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse application command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Run the Telegram publication automation service."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate settings, run startup tests, initialize dependencies, then exit without starting the scheduler",
    )
    parser.add_argument(
        "--check-telegram",
        action="store_true",
        help="validate TELEGRAM_BOT_TOKEN with Telegram getMe, then exit without starting the scheduler",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application until interrupted."""

    args = parse_args(argv if argv is not None else [])
    settings = get_settings()
    configure_logging(settings.log_level)

    if args.check_telegram:
        try:
            telegram_publisher = TelegramPublisher(settings)
            bot_name = telegram_publisher.validate_bot_token()
        except Exception as exc:
            logger.error("Telegram settings check failed: %s", exc)
            return 1
        logger.info(
            "Telegram bot token is valid for %s; publication channel is %s",
            bot_name,
            telegram_publisher.channel_id,
        )
        return 0

    if not run_startup_tests():
        return 1

    try:
        runtime = build_runtime(settings)
    except Exception as exc:
        logger.error("Application startup failed: %s", exc)
        return 1

    if args.check:
        logger.info("Runtime check completed successfully")
        return 0

    runtime.scheduler.start()
    logger.info("Content-plan scheduler started with exact item run times")
    logger.info("Telegram bot manual publication controls started")

    try:
        runtime.telegram_publisher.start_manual_polling()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping application")
        return 0
    except Exception as exc:
        logger.error("Telegram bot manual controls stopped with error: %s", exc)
        return 1
    finally:
        runtime.scheduler.shutdown(wait=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
