from __future__ import annotations

import pytest

from app.schemas import GeneratedPost, ImageAsset, News, PostStatus, PublishedPost
from app.service import create_and_publish_post


def make_news(index: int = 1) -> News:
    return News(
        title=f"News {index}",
        source_url=f"https://example.com/news/{index}",
        source_name="Example",
        summary="Short summary",
    )


def make_post(index: int = 1) -> GeneratedPost:
    return GeneratedPost(
        title=f"Post {index}",
        text="Telegram post text",
        image_prompt="Editorial illustration",
        source_url=f"https://example.com/news/{index}",
    )


class FakeAIClient:
    def __init__(
        self,
        news: list[News],
        *,
        fail_post: bool = False,
        fail_image: bool = False,
        last_error_message: str | None = None,
        last_image_error_message: str | None = None,
        skip_image: bool = False,
    ) -> None:
        self.news = news
        self.last_error_message = last_error_message
        self.last_image_error_message = last_image_error_message
        self.skip_image = skip_image
        self.fail_post = fail_post
        self.fail_image = fail_image
        self.generated_posts: list[News] = []
        self.image_posts: list[GeneratedPost] = []

    def find_fresh_news(self) -> list[News]:
        return self.news

    def generate_post(self, news: News) -> GeneratedPost:
        self.generated_posts.append(news)
        if self.fail_post:
            raise RuntimeError("text generation failed")
        url = str(news.source_url).rstrip("/")
        index = int(url.rsplit("/", 1)[1])
        return make_post(index)

    def generate_image(self, post: GeneratedPost) -> ImageAsset:
        self.image_posts.append(post)
        if self.fail_image:
            raise RuntimeError("image generation failed")
        if self.skip_image:
            return None
        return ImageAsset(data=b"image")


class FakeTelegramPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[GeneratedPost, ImageAsset | None]] = []

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        self.published.append((post, image))
        if self.fail:
            raise RuntimeError("telegram failed")
        return 777


class FakeRepository:
    def __init__(self, published_urls: set[str] | None = None) -> None:
        self.published_urls = published_urls or set()
        self.generated: list[GeneratedPost] = []
        self.published: list[tuple[str, int]] = []
        self.failed: list[tuple[str, str]] = []
        self.checked_urls: list[str] = []

    def is_published(self, source_url: str) -> bool:
        self.checked_urls.append(source_url)
        return source_url in self.published_urls

    def save_generated(self, post: GeneratedPost) -> PublishedPost:
        self.generated.append(post)
        return PublishedPost(
            source_url=post.source_url,
            title=post.title,
            text=post.text,
            status=PostStatus.GENERATED,
        )

    def mark_published(self, source_url: str, message_id: int) -> PublishedPost:
        self.published.append((source_url, message_id))
        return PublishedPost(
            source_url=source_url,
            title="Post 1",
            text="Telegram post text",
            status=PostStatus.PUBLISHED,
            telegram_message_id=message_id,
        )

    def mark_failed(self, source_url: str, error_message: str) -> PublishedPost:
        self.failed.append((source_url, error_message))
        return PublishedPost(
            source_url=source_url,
            title="Failed post",
            text="Failed text",
            status=PostStatus.FAILED,
            error_message=error_message,
        )


def test_successful_full_scenario() -> None:
    ai_client = FakeAIClient([make_news()])
    publisher = FakeTelegramPublisher()
    repository = FakeRepository()

    result = create_and_publish_post(ai_client, publisher, repository)

    assert result is not None
    assert result.status is PostStatus.PUBLISHED
    assert result.telegram_message_id == 777
    assert len(repository.generated) == 1
    assert repository.published == [("https://example.com/news/1", 777)]
    assert repository.failed == []
    assert len(publisher.published) == 1


def test_successful_scenario_reports_progress() -> None:
    progress_messages: list[str] = []

    result = create_and_publish_post(
        FakeAIClient([make_news()]),
        FakeTelegramPublisher(),
        FakeRepository(),
        progress_callback=progress_messages.append,
    )

    assert result is not None
    assert progress_messages == [
        "🔎 Ищу свежие новости через OpenRouter...",
        "✅ Новость найдена: News 1",
        "✍️ Генерирую текст поста через OpenRouter...",
        "💾 Сохраняю сгенерированный пост в БД...",
        "🖼️ Проверяю/генерирую изображение...",
        "✅ Изображение готово.",
        "📨 Публикую пост в Telegram...",
        "✅ Пост опубликован. Telegram message_id=777",
    ]



def test_reports_when_image_generation_returns_none() -> None:
    progress_messages: list[str] = []

    result = create_and_publish_post(
        FakeAIClient(
            [make_news()],
            skip_image=True,
            last_image_error_message="ENABLE_IMAGE_GENERATION=false",
        ),
        FakeTelegramPublisher(),
        FakeRepository(),
        progress_callback=progress_messages.append,
    )

    assert result is not None
    assert "⚠️ Изображение не сгенерировано: ENABLE_IMAGE_GENERATION=false" in progress_messages


def test_skips_already_published_news() -> None:
    first = make_news(1)
    second = make_news(2)
    repository = FakeRepository(published_urls={str(first.source_url)})
    ai_client = FakeAIClient([first, second])

    result = create_and_publish_post(ai_client, FakeTelegramPublisher(), repository)

    assert result is not None
    assert repository.checked_urls == ["https://example.com/news/1", "https://example.com/news/2"]
    assert ai_client.generated_posts == [second]
    assert repository.published == [("https://example.com/news/2", 777)]


def test_returns_none_when_there_are_no_new_news() -> None:
    repository = FakeRepository(published_urls={"https://example.com/news/1"})

    result = create_and_publish_post(FakeAIClient([make_news()]), FakeTelegramPublisher(), repository)

    assert result is None
    assert repository.generated == []
    assert repository.published == []
    assert repository.failed == []


def test_returns_none_when_news_list_is_empty() -> None:
    repository = FakeRepository()

    assert create_and_publish_post(FakeAIClient([]), FakeTelegramPublisher(), repository) is None
    assert repository.checked_urls == []


def test_text_generation_error_marks_failed() -> None:
    repository = FakeRepository()

    with pytest.raises(RuntimeError, match="text generation failed"):
        create_and_publish_post(FakeAIClient([make_news()], fail_post=True), FakeTelegramPublisher(), repository)

    assert repository.failed == [("https://example.com/news/1", "text generation failed")]
    assert repository.generated == []


def test_image_generation_error_marks_failed() -> None:
    repository = FakeRepository()

    with pytest.raises(RuntimeError, match="image generation failed"):
        create_and_publish_post(FakeAIClient([make_news()], fail_image=True), FakeTelegramPublisher(), repository)

    assert repository.failed == [("https://example.com/news/1", "image generation failed")]
    assert len(repository.generated) == 1


def test_telegram_error_marks_failed() -> None:
    repository = FakeRepository()

    with pytest.raises(RuntimeError, match="telegram failed"):
        create_and_publish_post(FakeAIClient([make_news()]), FakeTelegramPublisher(fail=True), repository)

    assert repository.failed == [("https://example.com/news/1", "telegram failed")]
    assert repository.published == []


def test_reports_ai_fetch_error_when_news_list_is_empty() -> None:
    progress_messages: list[str] = []

    result = create_and_publish_post(
        FakeAIClient([], last_error_message="OpenRouter request failed"),
        FakeTelegramPublisher(),
        FakeRepository(),
        progress_callback=progress_messages.append,
    )

    assert result is None
    assert progress_messages == [
        "🔎 Ищу свежие новости через OpenRouter...",
        "⚠️ OpenRouter не вернул новости из-за ошибки: OpenRouter request failed",
        "ℹ️ Свежих неопубликованных новостей не найдено.",
    ]

from app.service import approve_content_plan_item_publication, publish_due_content_plan_items
from app.schemas import ContentPlanItem, ContentPlanItemStatus
from datetime import datetime, timezone


class FakeContentPlanRepository:
    def __init__(self) -> None:
        self.items = [(5, ContentPlanItem(scheduled_at=datetime.now(timezone.utc), title="Plan post", text="Text", image_prompt=""))]
        self.published: list[tuple[int, int]] = []
        self.failed: list[tuple[int, str]] = []

    def get_due_items(self):
        return self.items

    def get_item(self, item_id: int) -> ContentPlanItem:
        assert item_id == self.items[0][0]
        return self.items[0][1]

    def mark_item_published(self, item_id: int, telegram_message_id: int) -> ContentPlanItem:
        self.published.append((item_id, telegram_message_id))
        return self.items[0][1].model_copy(update={"status": ContentPlanItemStatus.PUBLISHED, "telegram_message_id": telegram_message_id})

    def mark_item_failed(self, item_id: int, error_message: str) -> ContentPlanItem:
        self.failed.append((item_id, error_message))
        return self.items[0][1].model_copy(update={"status": ContentPlanItemStatus.FAILED, "error_message": error_message})


def test_publish_due_content_plan_items_publishes_due_items() -> None:
    repo = FakeContentPlanRepository()
    publisher = FakeTelegramPublisher()

    result = publish_due_content_plan_items(publisher, repo)

    assert len(result) == 1
    assert result[0].status is ContentPlanItemStatus.PUBLISHED
    assert repo.published == [(5, 777)]
    assert publisher.published[0][0].title == "Plan post"


def test_approve_content_plan_item_publication_keeps_item_scheduled() -> None:
    repo = FakeContentPlanRepository()
    publisher = FakeTelegramPublisher()

    result = approve_content_plan_item_publication(5, publisher, repo)

    assert result.status is ContentPlanItemStatus.SCHEDULED
    assert publisher.published == []
    assert repo.published == []
