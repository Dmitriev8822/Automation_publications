"""APScheduler setup for periodic publication jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def create_scheduler(job_func: Callable[[], Any], interval_minutes: int) -> BackgroundScheduler:
    """Create a background scheduler with one protected interval job.

    Exceptions raised by ``job_func`` are logged and swallowed so a single
    failed publication attempt does not stop future scheduled runs.
    """

    logger.info("Creating background scheduler: interval_minutes=%s", interval_minutes)
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        _protected_job(job_func, "Scheduled publication job failed"),
        trigger="interval",
        minutes=interval_minutes,
        id="publish_post",
        name="Create and publish Telegram post",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info("Scheduled publication job registered: id=publish_post interval_minutes=%s", interval_minutes)
    return scheduler


def add_content_plan_item_jobs(
    scheduler: BackgroundScheduler,
    job_func: Callable[[], Any],
    scheduled_items: list[tuple[int, datetime]],
) -> None:
    """Register one date job for each scheduled content-plan item.

    Existing jobs with the same item id are replaced, so the function can be
    safely called after saving a new content plan or on application startup.
    """

    for item_id, scheduled_at in scheduled_items:
        run_at = _ensure_timezone(scheduled_at)
        job_id = f"content_plan_item_{item_id}"
        scheduler.add_job(
            _protected_job(job_func, f"Content-plan publication job failed: item_id={item_id}"),
            trigger="date",
            run_date=run_at,
            id=job_id,
            name=f"Publish content-plan item {item_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )
        logger.info("Scheduled content-plan item job: id=%s run_date=%s", job_id, run_at.isoformat())


def create_content_plan_scheduler(
    job_func: Callable[[], Any],
    scheduled_items: list[tuple[int, datetime]] | None = None,
) -> BackgroundScheduler:
    """Create a scheduler that publishes content-plan items at their own times."""

    logger.info("Creating content-plan scheduler")
    scheduler = BackgroundScheduler()
    add_content_plan_item_jobs(scheduler, job_func, scheduled_items or [])
    return scheduler


def _protected_job(job_func: Callable[[], Any], error_message: str) -> Callable[[], None]:
    def protected_job() -> None:
        logger.info("Scheduled publication job started")
        try:
            job_func()
            logger.info("Scheduled publication job finished")
        except Exception:
            logger.exception(error_message)

    return protected_job


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
