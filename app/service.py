"""Business service for creating and publishing Telegram posts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from app.schemas import (
    ContentPlan,
    ContentPlanItem,
    ContentPlanItemStatus,
    GeneratedPost,
    ImageAsset,
    ManualPublicationDraft,
    News,
    PublishedPost,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


class AIClientProtocol(Protocol):
    """Public AI client contract used by the publication service."""

    def find_fresh_news(self) -> list[News]: ...

    def generate_post(self, news: News) -> GeneratedPost: ...

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None: ...

    def regenerate_content_plan(
        self, plan: "ContentPlan", instruction: str = ""
    ) -> "ContentPlan": ...

    def regenerate_content_plan_item_text(
        self, item: ContentPlanItem, instruction: str = ""
    ) -> ContentPlanItem: ...

    def regenerate_content_plan_item_image_prompt(
        self, item: ContentPlanItem, instruction: str = ""
    ) -> ContentPlanItem: ...


class TelegramPublisherProtocol(Protocol):
    """Public Telegram publisher contract used by the publication service."""

    def publish_post(
        self, post: GeneratedPost, image: ImageAsset | None = None
    ) -> int: ...


class PostRepositoryProtocol(Protocol):
    """Public repository contract used by the publication service."""

    def is_published(self, source_url: str) -> bool: ...

    def save_generated(self, post: GeneratedPost) -> PublishedPost: ...

    def mark_published(self, source_url: str, message_id: int) -> PublishedPost: ...

    def mark_failed(self, source_url: str, error_message: str) -> PublishedPost: ...


class ContentPlanRepositoryProtocol(Protocol):
    def get_due_items(self) -> list[tuple[int, ContentPlanItem]]: ...

    def mark_item_published(
        self, item_id: int, telegram_message_id: int
    ) -> ContentPlanItem: ...

    def mark_item_failed(self, item_id: int, error_message: str) -> ContentPlanItem: ...

    def mark_item_cancelled(
        self, item_id: int, error_message: str | None = None
    ) -> ContentPlanItem: ...

    def get_item(self, item_id: int) -> ContentPlanItem: ...

    def list_scheduled_items(self) -> list[tuple[int, ContentPlanItem]]: ...

    def update_item_content(
        self, item_id: int, item: ContentPlanItem
    ) -> ContentPlanItem: ...

    def get_plan(self, plan_id: int) -> ContentPlan: ...

    def mark_plan_cancelled(
        self, plan_id: int, error_message: str | None = None
    ) -> list[ContentPlanItem]: ...

    def replace_plan(
        self, plan_id: int, plan: ContentPlan
    ) -> tuple[int, ContentPlan]: ...


def create_manual_publication_draft(
    ai_client: AIClientProtocol,
    repository: PostRepositoryProtocol,
    progress_callback: ProgressCallback | None = None,
) -> ManualPublicationDraft | None:
    """Prepare a news publication draft without posting it to Telegram.

    This supports the manual menu flow: find an unpublished news item, generate
    text and image, then return the draft for explicit user approval. Nothing is
    persisted until the user accepts the draft.
    """

    _notify(progress_callback, "🔎 Ищу свежие новости через OpenRouter...")
    news = _find_first_unpublished_news(ai_client, repository)
    if news is None:
        ai_error = getattr(ai_client, "last_error_message", None)
        if ai_error:
            _notify(
                progress_callback,
                f"⚠️ OpenRouter не вернул новости из-за ошибки: {ai_error}",
            )
        _notify(progress_callback, "ℹ️ Свежих неопубликованных новостей не найдено.")
        return None

    _notify(progress_callback, f"✅ Новость найдена: {news.title}")
    _notify(progress_callback, "✍️ Генерирую текст поста через OpenRouter...")
    post = ai_client.generate_post(news)
    _notify(progress_callback, "🖼️ Проверяю/генерирую изображение...")
    image = ai_client.generate_image(post)
    _notify_image_result(progress_callback, ai_client, image)
    _notify(progress_callback, "👀 Черновик готов и ожидает согласования.")
    return ManualPublicationDraft(news=news, post=post, image=image)


def publish_manual_publication_draft(
    draft: ManualPublicationDraft,
    telegram_publisher: TelegramPublisherProtocol,
    repository: PostRepositoryProtocol,
) -> PublishedPost:
    """Persist and publish a user-approved manual publication draft."""

    source_url = str(draft.post.source_url)
    try:
        repository.save_generated(draft.post)
        message_id = telegram_publisher.publish_post(draft.post, draft.image)
        return repository.mark_published(source_url, message_id)
    except Exception as exc:
        _mark_failed(repository, source_url, exc)
        raise


def regenerate_manual_publication_text(
    draft: ManualPublicationDraft, ai_client: AIClientProtocol
) -> ManualPublicationDraft:
    """Regenerate text for a manual publication draft and refresh its image."""

    post = ai_client.generate_post(draft.news)
    image = ai_client.generate_image(post)
    return draft.model_copy(update={"post": post, "image": image})


def regenerate_manual_publication_image(
    draft: ManualPublicationDraft, ai_client: AIClientProtocol
) -> ManualPublicationDraft:
    """Regenerate only the image for a manual publication draft."""

    image = ai_client.generate_image(draft.post)
    return draft.model_copy(update={"image": image})


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
            ai_error = getattr(ai_client, "last_error_message", None)
            if ai_error:
                _notify(
                    progress_callback,
                    f"⚠️ OpenRouter не вернул новости из-за ошибки: {ai_error}",
                )
                logger.warning(
                    "No fresh news returned because AI client reported an error: %s",
                    ai_error,
                )
            _notify(
                progress_callback, "ℹ️ Свежих неопубликованных новостей не найдено."
            )
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
        _notify_image_result(progress_callback, ai_client, image)

        _notify(progress_callback, "📨 Публикую пост в Telegram...")
        logger.info("Publishing post to Telegram for source: %s", source_url)
        message_id = telegram_publisher.publish_post(generated_post, image)

        _notify(
            progress_callback, f"✅ Пост опубликован. Telegram message_id={message_id}"
        )
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
    logger.info("Calling AI client to find fresh news")
    news_items = ai_client.find_fresh_news()
    logger.info("AI client returned %d fresh news item(s)", len(news_items))
    for news in news_items:
        source_url = str(news.source_url)
        logger.info("Checking publication status in repository: %s", source_url)
        if repository.is_published(source_url):
            logger.info("Skipping already published news source: %s", source_url)
            continue
        logger.info("Selected unpublished news source: %s", source_url)
        return news
    return None


def _mark_failed(
    repository: PostRepositoryProtocol, source_url: str, exc: Exception
) -> None:
    error_message = str(exc) or exc.__class__.__name__
    logger.info("Marking post as failed for source: %s", source_url)
    try:
        repository.mark_failed(source_url, error_message)
    except Exception:
        logger.exception("Could not mark post as failed for source: %s", source_url)


def _notify_image_result(
    progress_callback: ProgressCallback | None,
    ai_client: AIClientProtocol,
    image: ImageAsset | None,
) -> None:
    if image is not None:
        _notify(progress_callback, "✅ Изображение готово.")
        return
    image_error = getattr(ai_client, "last_image_error_message", None)
    if image_error:
        _notify(progress_callback, f"⚠️ Изображение не сгенерировано: {image_error}")
    else:
        _notify(
            progress_callback, "ℹ️ Изображение не сгенерировано, публикую без картинки."
        )


def _notify(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        logger.exception("Could not send publication progress message")


def publish_due_content_plan_items(
    telegram_publisher: TelegramPublisherProtocol,
    content_plan_repository: ContentPlanRepositoryProtocol,
    ai_client: AIClientProtocol | None = None,
) -> list[ContentPlanItem]:
    """Publish all approved content-plan items whose scheduled time has come."""

    published_items: list[ContentPlanItem] = []
    due_items = content_plan_repository.get_due_items()
    logger.info("Found %d due content-plan item(s)", len(due_items))
    for item_id, item in due_items:
        generated_post = GeneratedPost(
            title=item.title,
            text=item.text,
            image_prompt=item.image_prompt,
            source_url=item.source_url or f"https://content-plan.local/items/{item_id}",
        )
        try:
            image = (
                ai_client.generate_image(generated_post)
                if ai_client is not None
                else None
            )
            message_id = telegram_publisher.publish_post(generated_post, image)
            published_items.append(
                content_plan_repository.mark_item_published(item_id, message_id)
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - keep scheduler alive and persist item failure
            logger.exception(
                "Content-plan item publication failed: item_id=%s", item_id
            )
            content_plan_repository.mark_item_failed(
                item_id, str(exc) or exc.__class__.__name__
            )
    return published_items


def approve_content_plan_item_publication(
    item_id: int,
    telegram_publisher: TelegramPublisherProtocol,
    content_plan_repository: ContentPlanRepositoryProtocol,
    ai_client: AIClientProtocol | None = None,
) -> ContentPlanItem:
    """Immediately publish one content-plan item after user approval.

    A reminder approval is an explicit user decision to publish the prepared
    post. The item is sent to Telegram right away and marked as published, so a
    later scheduler date-job will skip it because it is no longer scheduled.
    """

    item = content_plan_repository.get_item(item_id)
    if item.status != ContentPlanItemStatus.SCHEDULED:
        raise RuntimeError(
            f"Content-plan item {item_id} cannot be published from status {item.status.value}"
        )

    generated_post = GeneratedPost(
        title=item.title,
        text=item.text,
        image_prompt=item.image_prompt,
        source_url=item.source_url or f"https://content-plan.local/items/{item_id}",
    )
    try:
        image = (
            ai_client.generate_image(generated_post)
            if ai_client is not None and item.image_prompt
            else None
        )
        message_id = telegram_publisher.publish_post(generated_post, image)
        return content_plan_repository.mark_item_published(item_id, message_id)
    except Exception as exc:
        content_plan_repository.mark_item_failed(
            item_id, str(exc) or exc.__class__.__name__
        )
        raise


def reject_content_plan_item_publication(
    item_id: int,
    content_plan_repository: ContentPlanRepositoryProtocol,
    reason: str | None = None,
) -> ContentPlanItem:
    """Cancel one content-plan item after user refusal."""

    return content_plan_repository.mark_item_cancelled(
        item_id, reason or "User rejected publication"
    )


def regenerate_content_plan_item_text(
    item_id: int,
    ai_client: AIClientProtocol,
    content_plan_repository: ContentPlanRepositoryProtocol,
    instruction: str = "",
) -> ContentPlanItem:
    """Regenerate and persist text for one content-plan item."""

    item = content_plan_repository.get_item(item_id)
    regenerated = ai_client.regenerate_content_plan_item_text(item, instruction)
    return content_plan_repository.update_item_content(item_id, regenerated)


def regenerate_content_plan_item_image(
    item_id: int,
    ai_client: AIClientProtocol,
    content_plan_repository: ContentPlanRepositoryProtocol,
    instruction: str = "",
) -> ContentPlanItem:
    """Regenerate and persist image prompt for one content-plan item."""

    item = content_plan_repository.get_item(item_id)
    regenerated = ai_client.regenerate_content_plan_item_image_prompt(item, instruction)
    return content_plan_repository.update_item_content(item_id, regenerated)


def reject_content_plan_publication(
    plan_id: int,
    content_plan_repository: ContentPlanRepositoryProtocol,
    reason: str | None = None,
) -> list[ContentPlanItem]:
    """Cancel all scheduled items of one content plan after user deletion."""

    return content_plan_repository.mark_plan_cancelled(
        plan_id, reason or "User deleted content plan"
    )


def regenerate_content_plan(
    plan_id: int,
    ai_client: AIClientProtocol,
    content_plan_repository: ContentPlanRepositoryProtocol,
    instruction: str = "",
) -> tuple[int, ContentPlan]:
    """Regenerate and persist a whole content plan using a user instruction."""

    plan = content_plan_repository.get_plan(plan_id)
    regenerated = ai_client.regenerate_content_plan(plan, instruction)
    return content_plan_repository.replace_plan(plan_id, regenerated)
