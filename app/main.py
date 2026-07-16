"""Application entry point and dependency wiring."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.ai import AIClient
from app.config import Settings, get_settings, validate_runtime_settings
from app.database import PostRepository, init_db
from app.scheduler import create_scheduler
from app.service import create_and_publish_post
from app.telegram import TelegramPublisher

logger = logging.getLogger(__name__)

STARTUP_TEST_ARGS = ("tests", "-q")


def configure_logging(log_level: str) -> None:
    """Configure root logging for the runnable application."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def run_startup_tests(args: Sequence[str] = STARTUP_TEST_ARGS) -> bool:
    """Run fast startup checks and return whether they passed."""

    logger.info("Running startup tests: pytest %s", " ".join(args))
    exit_code = pytest.main(list(args))
    if exit_code != pytest.ExitCode.OK:
        logger.error("Startup tests failed with exit code %s", exit_code)
        return False
    logger.info("Startup tests passed")
    return True


def build_scheduler(settings: Settings):
    """Initialize infrastructure and return a configured scheduler."""

    validate_runtime_settings(settings)
    init_db()

    repository = PostRepository()
    ai_client = AIClient(settings)
    telegram_publisher = TelegramPublisher(settings)

    job = lambda: create_and_publish_post(ai_client, telegram_publisher, repository)
    return create_scheduler(job, settings.publish_interval_minutes)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse application command-line arguments."""

    parser = argparse.ArgumentParser(description="Run the Telegram publication automation service.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate settings, run startup tests, initialize dependencies, then exit without starting the scheduler",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the application until interrupted."""

    args = parse_args(argv if argv is not None else [])
    settings = get_settings()
    configure_logging(settings.log_level)

    if not run_startup_tests():
        return 1

    try:
        scheduler = build_scheduler(settings)
    except Exception as exc:
        logger.error("Application startup failed: %s", exc)
        return 1

    if args.check:
        logger.info("Runtime check completed successfully")
        return 0

    scheduler.start()
    logger.info("Scheduler started with %s minute interval", settings.publish_interval_minutes)

    stop_event = signal.pause if hasattr(signal, "pause") else None
    try:
        if stop_event is not None:
            while True:
                stop_event()
        else:
            import time

            while True:
                time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping application")
    finally:
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
