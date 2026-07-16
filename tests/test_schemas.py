import pytest
from pydantic import ValidationError

from app.schemas import GeneratedPost, ImageAsset, News, PostStatus, PublishedPost


def test_news_requires_valid_source_url() -> None:
    news = News(
        title="Title",
        source_url="https://example.com/news",
        source_name="Example",
        summary="Summary",
    )

    assert str(news.source_url) == "https://example.com/news"

    with pytest.raises(ValidationError):
        News(title="Title", source_url="not-a-url", source_name="Example", summary="Summary")


def test_generated_post_text_must_not_be_empty() -> None:
    post = GeneratedPost(
        title="Title",
        text="Post text",
        image_prompt="Image prompt",
        source_url="https://example.com/news",
    )

    assert post.text == "Post text"

    with pytest.raises(ValidationError):
        GeneratedPost(
            title="Title",
            text="",
            image_prompt="Image prompt",
            source_url="https://example.com/news",
        )

    with pytest.raises(ValidationError):
        GeneratedPost(
            title="Title",
            text="   ",
            image_prompt="Image prompt",
            source_url="https://example.com/news",
        )


def test_image_asset_requires_data_url_or_file_path() -> None:
    assert ImageAsset(data=b"image").data == b"image"
    assert str(ImageAsset(url="https://example.com/image.png").url) == "https://example.com/image.png"
    assert str(ImageAsset(file_path="/tmp/image.png").file_path) == "/tmp/image.png"

    with pytest.raises(ValidationError):
        ImageAsset()


def test_published_post_requires_post_status() -> None:
    published = PublishedPost(
        source_url="https://example.com/news",
        title="Title",
        text="Post text",
        status=PostStatus.PUBLISHED,
        telegram_message_id=123,
    )

    assert published.status is PostStatus.PUBLISHED

    with pytest.raises(ValidationError):
        PublishedPost(
            source_url="https://example.com/news",
            title="Title",
            text="Post text",
            status="unknown",
        )
