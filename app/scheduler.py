"""APScheduler setup for periodic publication jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def create_scheduler(job_func: Callable[[], Any], interval_minutes: int) -> BackgroundScheduler:
    """Create a background scheduler with one protected interval job.

    Exceptions raised by ``job_func`` are logged and swallowed so a single
    failed publication attempt does not stop future scheduled runs.
    """

    scheduler = BackgroundScheduler()

    def protected_job() -> None:
        try:
            job_func()
        except Exception:
            logger.exception("Scheduled publication job failed")

    scheduler.add_job(
        protected_job,
        trigger="interval",
        minutes=interval_minutes,
        id="publish_post",
        name="Create and publish Telegram post",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
