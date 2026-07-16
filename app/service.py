"""Business service for creating and publishing Telegram posts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from app.schemas import GeneratedPost, ImageAsset, News, PublishedPost

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


class AIClientProtocol(Protocol):
    """Public AI client contract used by the publication service."""

    def find_fresh_news(self) -> list[News]: ...

    def generate_post(self, news: News) -> GeneratedPost: ...

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None: ...


class TelegramPublisherProtocol(Protocol):
    """Public Telegram publisher contract used by the publication service."""

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int: ...


class PostRepositoryProtocol(Protocol):
    """Public repository contract used by the publication service."""

    def is_published(self, source_url: str) -> bool: ...

    def save_generated(self, post: GeneratedPost) -> PublishedPost: ...

    def mark_published(self, source_url: str, message_id: int) -> PublishedPost: ...

    def mark_failed(self, source_url: str, error_message: str) -> PublishedPost: ...


def create_and_publish_post(
    ai_client: AIClientProtocol,
    telegram_publisher: TelegramPublisherProtocol,
    repository: PostRepositoryProtocol,
    progress_callback: ProgressCallback | None = None,
) -> PublishedPost | None:
    """Create and publish the first fresh unpublished news item.

    Returns the persisted published post, or ``None`` when all fresh news are
    already published or no news are available. Exceptions from generation or
    publication are re-raised after the failure status is recorded whenever the
    source URL is already known.
    """

    source_url: str | None = None
    _notify(progress_callback, "🔎 Ищу свежие новости через OpenRouter...")
    logger.info("Looking for fresh news")
    try:
        news = _find_first_unpublished_news(ai_client, repository)
        if news is None:
            _notify(progress_callback, "ℹ️ Свежих неопубликованных новостей не найдено.")
            logger.info("No unpublished fresh news found")
            return None

        source_url = str(news.source_url)
        _notify(progress_callback, f"✅ Новость найдена: {news.title}")
        _notify(progress_callback, "✍️ Генерирую текст поста через OpenRouter...")
        logger.info("Generating post for news source: %s", source_url)
        generated_post = ai_client.generate_post(news)
        source_url = str(generated_post.source_url)

        _notify(progress_callback, "💾 Сохраняю сгенерированный пост в БД...")
        logger.info("Saving generated post for source: %s", source_url)
        repository.save_generated(generated_post)

        _notify(progress_callback, "🖼️ Проверяю/генерирую изображение...")
        logger.info("Generating image for source: %s", source_url)
        image = ai_client.generate_image(generated_post)

        _notify(progress_callback, "📨 Публикую пост в Telegram...")
        logger.info("Publishing post to Telegram for source: %s", source_url)
        message_id = telegram_publisher.publish_post(generated_post, image)

        _notify(progress_callback, f"✅ Пост опубликован. Telegram message_id={message_id}")
        logger.info("Marking post as published for source: %s", source_url)
        return repository.mark_published(source_url, message_id)
    except Exception as exc:
        if source_url is not None:
            _notify(progress_callback, f"❌ Ошибка: {exc}")
            _mark_failed(repository, source_url, exc)
        logger.exception("Post creation and publication failed")
        raise


def _find_first_unpublished_news(
    ai_client: AIClientProtocol,
    repository: PostRepositoryProtocol,
) -> News | None:
    news_items = ai_client.find_fresh_news()
    logger.info("Found %d fresh news items", len(news_items))
    for news in news_items:
        source_url = str(news.source_url)
        if repository.is_published(source_url):
            logger.info("Skipping already published news source: %s", source_url)
            continue
        logger.info("Selected unpublished news source: %s", source_url)
        return news
    return None


def _mark_failed(repository: PostRepositoryProtocol, source_url: str, exc: Exception) -> None:
    error_message = str(exc) or exc.__class__.__name__
    logger.info("Marking post as failed for source: %s", source_url)
    try:
        repository.mark_failed(source_url, error_message)
    except Exception:
        logger.exception("Could not mark post as failed for source: %s", source_url)


def _notify(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        logger.exception("Could not send publication progress message")
