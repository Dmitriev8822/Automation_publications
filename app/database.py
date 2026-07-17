"""SQLite persistence for generated and published posts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Callable

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import get_settings
from app.schemas import (
    ContentPlan,
    ContentPlanItem,
    ContentPlanItemStatus,
    GeneratedPost,
    PostStatus,
    PublishedPost,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_app_timezone_naive(value: datetime, app_timezone: ZoneInfo) -> datetime:
    """Convert a datetime to naive application-local time for SQLite storage."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=app_timezone)
    return value.astimezone(app_timezone).replace(tzinfo=None)


def _from_app_timezone_naive(value: datetime, app_timezone: ZoneInfo) -> datetime:
    """Treat datetimes loaded from SQLite as application-local time."""

    if value.tzinfo is None:
        return value.replace(tzinfo=app_timezone)
    return value.astimezone(app_timezone)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
)


class PostRecord(Base):
    """Stored publication record keyed by the source news URL."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PostStatus.GENERATED.value
    )
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )


class ContentPlanRecord(Base):
    """Stored user-approved content plan."""

    __tablename__ = "content_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    items: Mapped[list["ContentPlanItemRecord"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ContentPlanItemRecord.scheduled_at",
    )


class ContentPlanItemRecord(Base):
    """Stored scheduled content-plan publication item."""

    __tablename__ = "content_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("content_plans.id"), nullable=False, index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ContentPlanItemStatus.SCHEDULED.value
    )
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
    plan: Mapped[ContentPlanRecord] = relationship(back_populates="items")


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create a parent directory for file-based SQLite databases."""

    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database:
        return

    if url.database in {":memory:", ""}:
        return

    path = Path(url.database).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Ensured SQLite parent directory exists: %s", path.parent)


def init_db() -> None:
    """Create database tables for the configured engine."""

    logger.info("Initializing database: url=%s", settings.database_url)
    _ensure_sqlite_parent_dir(settings.database_url)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables are ready")


class PostRepository:
    """Repository hiding SQLAlchemy details from business services."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def is_published(self, source_url: str) -> bool:
        with self._session_factory() as session:
            logger.info("Checking whether source is published: %s", source_url)
            record = self._get_record(session, source_url)
            is_published = (
                record is not None and record.status == PostStatus.PUBLISHED.value
            )
            logger.info(
                "Publication status checked: source_url=%s is_published=%s",
                source_url,
                is_published,
            )
            return is_published

    def save_generated(self, post: GeneratedPost) -> PublishedPost:
        with self._session_factory() as session:
            logger.info("Saving generated post: source_url=%s", post.source_url)
            record = PostRecord(
                source_url=str(post.source_url),
                title=post.title,
                text=post.text,
                status=PostStatus.GENERATED.value,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info(
                "Generated post saved: id=%s source_url=%s",
                record.id,
                record.source_url,
            )
            return self._to_schema(record)

    def mark_published(
        self, source_url: str, telegram_message_id: int
    ) -> PublishedPost:
        with self._session_factory() as session:
            logger.info(
                "Marking post as published: source_url=%s message_id=%s",
                source_url,
                telegram_message_id,
            )
            record = self._require_record(session, source_url)
            record.status = PostStatus.PUBLISHED.value
            record.telegram_message_id = telegram_message_id
            record.error_message = None
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            logger.info(
                "Post marked as published: id=%s source_url=%s",
                record.id,
                record.source_url,
            )
            return self._to_schema(record)

    def mark_failed(self, source_url: str, error_message: str) -> PublishedPost:
        with self._session_factory() as session:
            logger.info(
                "Marking post as failed: source_url=%s error=%s",
                source_url,
                error_message,
            )
            record = self._require_record(session, source_url)
            record.status = PostStatus.FAILED.value
            record.error_message = error_message
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            logger.info(
                "Post marked as failed: id=%s source_url=%s",
                record.id,
                record.source_url,
            )
            return self._to_schema(record)

    def get_by_source_url(self, source_url: str) -> PublishedPost | None:
        with self._session_factory() as session:
            logger.info("Loading post by source_url: %s", source_url)
            record = self._get_record(session, source_url)
            return self._to_schema(record) if record else None

    @staticmethod
    def _get_record(session: Session, source_url: str) -> PostRecord | None:
        return session.scalar(
            select(PostRecord).where(PostRecord.source_url == str(source_url))
        )

    @classmethod
    def _require_record(cls, session: Session, source_url: str) -> PostRecord:
        record = cls._get_record(session, source_url)
        if record is None:
            raise LookupError(f"Post with source_url '{source_url}' was not found")
        return record

    @staticmethod
    def _to_schema(record: PostRecord) -> PublishedPost:
        return PublishedPost(
            id=record.id,
            source_url=record.source_url,
            title=record.title,
            text=record.text,
            status=PostStatus(record.status),
            telegram_message_id=record.telegram_message_id,
            error_message=record.error_message,
        )


class ContentPlanRepository:
    """Repository for approved content plans and their scheduled items."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        app_timezone: ZoneInfo | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._app_timezone = app_timezone or get_settings().timezone

    def save_plan(self, plan: ContentPlan) -> int:
        """Persist an approved content plan and return its database id."""

        with self._session_factory() as session:
            record = ContentPlanRecord(
                title=plan.title,
                raw_request=plan.raw_request,
                period_start=_to_app_timezone_naive(
                    plan.period_start, self._app_timezone
                ),
                period_end=_to_app_timezone_naive(plan.period_end, self._app_timezone),
                items=[
                    ContentPlanItemRecord(
                        scheduled_at=_to_app_timezone_naive(
                            item.scheduled_at, self._app_timezone
                        ),
                        title=item.title,
                        text=item.text,
                        image_prompt=item.image_prompt,
                        source_url=str(item.source_url) if item.source_url else None,
                        status=item.status.value,
                    )
                    for item in plan.items
                ],
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id

    def get_due_items(
        self, now: datetime | None = None
    ) -> list[tuple[int, ContentPlanItem]]:
        """Return scheduled content-plan items due for publication."""

        due_at = _to_app_timezone_naive(now or _utc_now(), self._app_timezone)
        with self._session_factory() as session:
            records = session.scalars(
                select(ContentPlanItemRecord)
                .where(
                    ContentPlanItemRecord.status
                    == ContentPlanItemStatus.SCHEDULED.value
                )
                .where(ContentPlanItemRecord.scheduled_at <= due_at)
                .order_by(ContentPlanItemRecord.scheduled_at)
            ).all()
            return [(record.id, self._item_to_schema(record)) for record in records]

    def get_scheduled_item_slots(self) -> list[tuple[int, datetime]]:
        """Return ids and planned times for all not-yet-published content-plan items."""

        with self._session_factory() as session:
            records = session.scalars(
                select(ContentPlanItemRecord)
                .where(
                    ContentPlanItemRecord.status
                    == ContentPlanItemStatus.SCHEDULED.value
                )
                .order_by(ContentPlanItemRecord.scheduled_at)
            ).all()
            return [
                (
                    record.id,
                    _from_app_timezone_naive(record.scheduled_at, self._app_timezone),
                )
                for record in records
            ]

    def mark_item_published(
        self, item_id: int, telegram_message_id: int
    ) -> ContentPlanItem:
        with self._session_factory() as session:
            record = self._require_item(session, item_id)
            record.status = ContentPlanItemStatus.PUBLISHED.value
            record.telegram_message_id = telegram_message_id
            record.error_message = None
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._item_to_schema(record)

    def mark_item_failed(self, item_id: int, error_message: str) -> ContentPlanItem:
        with self._session_factory() as session:
            record = self._require_item(session, item_id)
            record.status = ContentPlanItemStatus.FAILED.value
            record.error_message = error_message
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._item_to_schema(record)

    def mark_item_cancelled(
        self, item_id: int, error_message: str | None = None
    ) -> ContentPlanItem:
        """Cancel a scheduled content-plan item after user refusal."""

        with self._session_factory() as session:
            record = self._require_item(session, item_id)
            record.status = ContentPlanItemStatus.CANCELLED.value
            record.error_message = error_message
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._item_to_schema(record)

    def get_item(self, item_id: int) -> ContentPlanItem:
        """Load one content-plan item by id."""

        with self._session_factory() as session:
            return self._item_to_schema(self._require_item(session, item_id))

    def update_item_content(
        self, item_id: int, item: ContentPlanItem
    ) -> ContentPlanItem:
        """Update editable text fields of a scheduled content-plan item."""

        with self._session_factory() as session:
            record = self._require_item(session, item_id)
            record.title = item.title
            record.text = item.text
            record.image_prompt = item.image_prompt
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._item_to_schema(record)

    @staticmethod
    def _require_item(session: Session, item_id: int) -> ContentPlanItemRecord:
        record = session.get(ContentPlanItemRecord, item_id)
        if record is None:
            raise LookupError(f"Content plan item with id '{item_id}' was not found")
        return record

    def _item_to_schema(self, record: ContentPlanItemRecord) -> ContentPlanItem:
        return ContentPlanItem(
            scheduled_at=_from_app_timezone_naive(
                record.scheduled_at, self._app_timezone
            ),
            title=record.title,
            text=record.text,
            image_prompt=record.image_prompt,
            source_url=record.source_url,
            status=ContentPlanItemStatus(record.status),
            telegram_message_id=record.telegram_message_id,
            error_message=record.error_message,
        )
