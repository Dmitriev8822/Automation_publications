from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, PostRecord, PostRepository, _ensure_sqlite_parent_dir
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
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
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

    published = repo.mark_published(
        str(generated_post.source_url), telegram_message_id=456
    )

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


def test_ensure_sqlite_parent_dir_creates_missing_directory(tmp_path):
    db_path = tmp_path / "nested" / "publications.db"

    _ensure_sqlite_parent_dir(f"sqlite:///{db_path}")

    assert db_path.parent.is_dir()


from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.database import ContentPlanRepository
from app.schemas import ContentPlan, ContentPlanItemStatus


def make_content_plan() -> ContentPlan:
    now = datetime.now(timezone.utc)
    return ContentPlan(
        title="План на неделю",
        period_start=now - timedelta(days=1),
        period_end=now + timedelta(days=1),
        raw_request="план",
        items=[
            {
                "scheduled_at": now - timedelta(minutes=1),
                "title": "Due",
                "text": "Due text",
                "image_prompt": "",
            },
            {
                "scheduled_at": now + timedelta(hours=1),
                "title": "Future",
                "text": "Future text",
                "image_prompt": "",
            },
        ],
    )


def test_content_plan_repository_saves_and_returns_due_items(repository):
    _, engine = repository
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    repo = ContentPlanRepository(SessionLocal)

    plan_id = repo.save_plan(make_content_plan())
    due_items = repo.get_due_items()

    assert plan_id is not None
    assert len(due_items) == 1
    item_id, item = due_items[0]
    assert item.title == "Due"

    published = repo.mark_item_published(item_id, 321)
    assert published.status is ContentPlanItemStatus.PUBLISHED
    assert published.telegram_message_id == 321
    assert repo.get_due_items() == []


def test_content_plan_repository_returns_scheduled_item_slots(repository):
    _, engine = repository
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    repo = ContentPlanRepository(SessionLocal)

    repo.save_plan(make_content_plan())
    slots = repo.get_scheduled_item_slots()

    assert len(slots) == 2
    assert all(isinstance(item_id, int) for item_id, _scheduled_at in slots)
    assert slots[0][1] <= slots[1][1]


def test_content_plan_repository_treats_naive_times_as_app_timezone(repository):
    _, engine = repository
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    repo = ContentPlanRepository(SessionLocal, app_timezone=ZoneInfo("Europe/Moscow"))
    plan = ContentPlan(
        title="План",
        period_start=datetime(2026, 7, 17, 13, 0),
        period_end=datetime(2026, 7, 17, 14, 0),
        items=[
            {
                "scheduled_at": datetime(2026, 7, 17, 13, 35),
                "title": "Local",
                "text": "Text",
            }
        ],
    )

    repo.save_plan(plan)
    slots = repo.get_scheduled_item_slots()

    assert slots[0][1].isoformat() == "2026-07-17T13:35:00+03:00"
    assert (
        repo.get_due_items(
            datetime(2026, 7, 17, 13, 34, tzinfo=ZoneInfo("Europe/Moscow"))
        )
        == []
    )
    assert (
        len(
            repo.get_due_items(
                datetime(2026, 7, 17, 13, 35, tzinfo=ZoneInfo("Europe/Moscow"))
            )
        )
        == 1
    )


from app.database import ReminderSettingsRepository


def test_reminder_settings_repository_persists_enable_and_disable(repository):
    _, engine = repository
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    repo = ReminderSettingsRepository(SessionLocal)

    assert repo.get_settings() == (False, None, None)

    repo.enable(5, 777)

    assert repo.get_settings() == (True, 5, "777")

    repo.disable()

    assert repo.get_settings() == (False, None, "777")
