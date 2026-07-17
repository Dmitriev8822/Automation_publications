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
from app.database import ContentPlanRepository, PostRepository, init_db
from app.scheduler import create_scheduler
from app.service import create_and_publish_post, publish_due_content_plan_items
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
    previous_handler_levels = [(handler, handler.level) for handler in root_logger.handlers]
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
    ai_client = AIClient(settings)
    telegram_publisher = TelegramPublisher(settings)

    def scheduled_job():
        try:
            create_and_publish_post(ai_client, telegram_publisher, repository)
        except Exception:
            logger.exception("Scheduled news publication failed; continuing with content-plan items")
        publish_due_content_plan_items(telegram_publisher, content_plan_repository)
    manual_job = lambda progress: create_and_publish_post(
        ai_client,
        telegram_publisher,
        repository,
        progress_callback=progress,
    )
    telegram_publisher.register_manual_publish_handler(manual_job)
    telegram_publisher.register_content_plan_handler(ai_client.generate_content_plan, content_plan_repository.save_plan)

    logger.info("Creating scheduler with interval_minutes=%s", settings.publish_interval_minutes)
    scheduler = create_scheduler(scheduled_job, settings.publish_interval_minutes)
    return ApplicationRuntime(scheduler=scheduler, telegram_publisher=telegram_publisher)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse application command-line arguments."""

    parser = argparse.ArgumentParser(description="Run the Telegram publication automation service.")
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
    logger.info("Scheduler started with %s minute interval", settings.publish_interval_minutes)
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
