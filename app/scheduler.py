"""APScheduler setup for periodic publication jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings

logger = logging.getLogger(__name__)


def create_scheduler(settings: Settings, job: Callable[[], object]) -> BackgroundScheduler:
    """Create a scheduler that runs the publication job on the configured interval."""

    scheduler = BackgroundScheduler()

    def safe_job() -> None:
        try:
            job()
        except Exception:
            logger.exception("Scheduled publication job failed")

    scheduler.add_job(
        safe_job,
        trigger="interval",
        minutes=settings.publish_interval_minutes,
        id="create_and_publish_post",
        replace_existing=True,
    )
    return scheduler
