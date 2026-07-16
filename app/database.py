"""SQLite persistence for generated and published posts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings
from app.schemas import GeneratedPost, PostStatus, PublishedPost


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


class PostRecord(Base):
    """Stored publication record keyed by the source news URL."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=PostStatus.GENERATED.value)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create a parent directory for file-based SQLite databases."""

    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database:
        return

    if url.database in {":memory:", ""}:
        return

    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    """Create database tables for the configured engine."""

    _ensure_sqlite_parent_dir(settings.database_url)
    Base.metadata.create_all(bind=engine)


class PostRepository:
    """Repository hiding SQLAlchemy details from business services."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def is_published(self, source_url: str) -> bool:
        with self._session_factory() as session:
            record = self._get_record(session, source_url)
            return record is not None and record.status == PostStatus.PUBLISHED.value

    def save_generated(self, post: GeneratedPost) -> PublishedPost:
        with self._session_factory() as session:
            record = PostRecord(
                source_url=str(post.source_url),
                title=post.title,
                text=post.text,
                status=PostStatus.GENERATED.value,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_schema(record)

    def mark_published(self, source_url: str, telegram_message_id: int) -> PublishedPost:
        with self._session_factory() as session:
            record = self._require_record(session, source_url)
            record.status = PostStatus.PUBLISHED.value
            record.telegram_message_id = telegram_message_id
            record.error_message = None
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._to_schema(record)

    def mark_failed(self, source_url: str, error_message: str) -> PublishedPost:
        with self._session_factory() as session:
            record = self._require_record(session, source_url)
            record.status = PostStatus.FAILED.value
            record.error_message = error_message
            record.updated_at = _utc_now()
            session.commit()
            session.refresh(record)
            return self._to_schema(record)

    def get_by_source_url(self, source_url: str) -> PublishedPost | None:
        with self._session_factory() as session:
            record = self._get_record(session, source_url)
            return self._to_schema(record) if record else None

    @staticmethod
    def _get_record(session: Session, source_url: str) -> PostRecord | None:
        return session.scalar(select(PostRecord).where(PostRecord.source_url == str(source_url)))

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
