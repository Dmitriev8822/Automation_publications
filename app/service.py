"""Main business process for creating and publishing Telegram posts."""

from __future__ import annotations

import logging

from app.ai import AIClient
from app.database import PostRepository
from app.schemas import PostStatus, PublishedPost
from app.telegram import TelegramPublisher

logger = logging.getLogger(__name__)


def create_and_publish_post(
    ai_client: AIClient,
    telegram_publisher: TelegramPublisher,
    repository: PostRepository,
) -> PublishedPost | None:
    """Find one unpublished news item, generate content, publish it, and save result."""

    news_items = ai_client.find_fresh_news()
    logger.info("Found %s candidate news items", len(news_items))

    for news in news_items:
        source_url = str(news.source_url)
        if repository.is_news_published(source_url):
            logger.info("Skipping already published news: %s", source_url)
            continue

        generated_post = ai_client.generate_post(news)
        try:
            image = ai_client.generate_image(generated_post)
            telegram_message_id = telegram_publisher.publish_post(generated_post, image)
        except Exception as exc:
            logger.exception("Failed to publish generated post for %s", source_url)
            return repository.save_post(
                generated_post,
                status=PostStatus.FAILED,
                error_message=str(exc),
            )

        return repository.save_post(
            generated_post,
            status=PostStatus.PUBLISHED,
            telegram_message_id=telegram_message_id,
        )

    logger.info("No unpublished news found")
    return None
