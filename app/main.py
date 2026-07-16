"""Application entry point."""

from __future__ import annotations

import logging
import subprocess
import time

from app.ai import OpenRouterAIClient
from app.config import get_settings, validate_runtime_settings
from app.database import PostRepository, create_session_factory, init_db
from app.scheduler import create_scheduler
from app.service import create_and_publish_post
from app.telegram import TeleBotPublisher


def run_startup_tests() -> None:
    """Run quick tests before starting the scheduler."""

    result = subprocess.run(["pytest", "tests"], check=False)
    if result.returncode != 0:
        raise RuntimeError("Startup tests failed")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    validate_runtime_settings(settings)
    run_startup_tests()

    session_factory = create_session_factory(settings.database_url)
    init_db(session_factory)
    repository = PostRepository(session_factory)
    ai_client = OpenRouterAIClient(settings)
    telegram_publisher = TeleBotPublisher(settings)

    scheduler = create_scheduler(
        settings,
        lambda: create_and_publish_post(ai_client, telegram_publisher, repository),
    )
    scheduler.start()

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    main()
