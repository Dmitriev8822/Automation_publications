import pytest
from pydantic import ValidationError

from app.schemas import GeneratedPost, ImageAsset, News, PostStatus, PublishedPost


def test_news_requires_valid_url():
    with pytest.raises(ValidationError):
        News(title="Title", source_url="not-url", source_name="Source", summary="Summary")


def test_generated_post_text_cannot_be_blank():
    with pytest.raises(ValidationError):
        GeneratedPost(title="Title", text="   ", image_prompt="Prompt", source_url="https://example.com/news")


def test_image_asset_requires_source():
    with pytest.raises(ValidationError):
        ImageAsset()


def test_published_post_accepts_status_enum():
    post = PublishedPost(
        source_url="https://example.com/news",
        title="Title",
        text="Text",
        status=PostStatus.PUBLISHED,
        telegram_message_id=123,
    )

    assert post.status == PostStatus.PUBLISHED
