"""Database models and repository for published Telegram posts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.schemas import GeneratedPost, PostStatus, PublishedPost


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class PostRecord(Base):
    """SQLAlchemy representation of a generated or published post."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(2048), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=PostStatus.GENERATED.value)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_schema(self) -> PublishedPost:
        return PublishedPost(
            id=self.id,
            source_url=self.source_url,
            title=self.title,
            text=self.text,
            status=PostStatus(self.status),
            telegram_message_id=self.telegram_message_id,
            error_message=self.error_message,
        )


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory for the configured database."""

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(session_factory: sessionmaker[Session]) -> None:
    """Create database tables for a session factory."""

    Base.metadata.create_all(session_factory.kw["bind"])


class PostRepository:
    """Repository hiding SQLAlchemy details from service code."""

    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def is_news_published(self, source_url: str) -> bool:
        with self.session_scope() as session:
            stmt = select(PostRecord.id).where(PostRecord.source_url == source_url, PostRecord.status == PostStatus.PUBLISHED.value)
            return session.execute(stmt).first() is not None

    def save_post(
        self,
        post: GeneratedPost,
        status: PostStatus,
        telegram_message_id: int | None = None,
        error_message: str | None = None,
    ) -> PublishedPost:
        with self.session_scope() as session:
            record = PostRecord(
                source_url=str(post.source_url),
                title=post.title,
                text=post.text,
                status=status.value,
                telegram_message_id=telegram_message_id,
                error_message=error_message,
            )
            session.add(record)
            session.flush()
            return record.to_schema()
