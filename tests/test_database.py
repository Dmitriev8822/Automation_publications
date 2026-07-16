from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, PostRecord, PostRepository
from app.schemas import GeneratedPost, PostStatus


@pytest.fixture()
def repository():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    return PostRepository(SessionLocal), engine


@pytest.fixture()
def generated_post() -> GeneratedPost:
    return GeneratedPost(
        title="Important automation news",
        text="Generated Telegram post text",
        image_prompt="news illustration",
        source_url="https://example.com/news/1",
    )


def test_creates_posts_table(repository):
    _, engine = repository

    inspector = inspect(engine)

    assert "posts" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("posts")}
    assert {
        "id",
        "source_url",
        "title",
        "text",
        "status",
        "telegram_message_id",
        "error_message",
        "created_at",
        "updated_at",
    }.issubset(columns)


def test_save_generated_post(repository, generated_post):
    repo, _ = repository

    saved = repo.save_generated(generated_post)

    assert saved.id is not None
    assert str(saved.source_url) == str(generated_post.source_url)
    assert saved.title == generated_post.title
    assert saved.text == generated_post.text
    assert saved.status is PostStatus.GENERATED
    assert saved.telegram_message_id is None
    assert saved.error_message is None


def test_is_published_for_published_and_unpublished_urls(repository, generated_post):
    repo, _ = repository
    repo.save_generated(generated_post)

    assert repo.is_published(str(generated_post.source_url)) is False

    repo.mark_published(str(generated_post.source_url), telegram_message_id=123)

    assert repo.is_published(str(generated_post.source_url)) is True
    assert repo.is_published("https://example.com/news/missing") is False


def test_source_url_is_unique(repository, generated_post):
    repo, _ = repository
    repo.save_generated(generated_post)

    with pytest.raises(IntegrityError):
        repo.save_generated(generated_post)


def test_mark_published(repository, generated_post):
    repo, _ = repository
    repo.save_generated(generated_post)

    published = repo.mark_published(str(generated_post.source_url), telegram_message_id=456)

    assert published.status is PostStatus.PUBLISHED
    assert published.telegram_message_id == 456
    assert published.error_message is None


def test_mark_failed(repository, generated_post):
    repo, _ = repository
    repo.save_generated(generated_post)

    failed = repo.mark_failed(str(generated_post.source_url), "Telegram API error")

    assert failed.status is PostStatus.FAILED
    assert failed.error_message == "Telegram API error"


def test_get_by_source_url(repository, generated_post):
    repo, _ = repository
    repo.save_generated(generated_post)

    found = repo.get_by_source_url(str(generated_post.source_url))

    assert found is not None
    assert found.status is PostStatus.GENERATED
    assert repo.get_by_source_url("https://example.com/news/missing") is None
