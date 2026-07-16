"""Tests for OpenRouter AI client without real API calls."""

from __future__ import annotations

import json

from app.ai import AIClient
from app.config import Settings
from app.schemas import GeneratedPost, News


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeHTTPClient:
    def __init__(self, contents: list[object]) -> None:
        self.contents = contents
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        content = self.contents.pop(0)
        return FakeResponse({"choices": [{"message": {"content": content}}]})


def make_settings(**overrides) -> Settings:
    defaults = {
        "openrouter_api_key": "test-key",
        "max_news_items": 2,
        "enable_image_generation": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_find_fresh_news_parses_successful_response() -> None:
    content = json.dumps(
        {
            "news": [
                {
                    "title": "AI release",
                    "source_url": "https://example.com/ai-release",
                    "source_name": "Example",
                    "summary": "A new AI system was released.",
                    "published_at": "2026-07-16T10:00:00Z",
                },
                {
                    "title": "Automation update",
                    "source_url": "https://example.com/automation",
                    "source_name": "Example",
                    "summary": "Automation tooling was updated.",
                },
            ]
        }
    )
    client = AIClient(settings=make_settings(), http_client=FakeHTTPClient([content]))

    news = client.find_fresh_news()

    assert len(news) == 2
    assert all(isinstance(item, News) for item in news)
    assert news[0].title == "AI release"


def test_generate_post_parses_generated_post() -> None:
    content = json.dumps(
        {
            "title": "AI release",
            "text": "Fresh Telegram-ready post",
            "image_prompt": "Editorial illustration of AI automation",
            "source_url": "https://example.com/ai-release",
        }
    )
    client = AIClient(settings=make_settings(), http_client=FakeHTTPClient([content]))
    news = News(
        title="AI release",
        source_url="https://example.com/ai-release",
        source_name="Example",
        summary="A new AI system was released.",
    )

    post = client.generate_post(news)

    assert isinstance(post, GeneratedPost)
    assert post.text == "Fresh Telegram-ready post"
    assert post.image_prompt == "Editorial illustration of AI automation"


def test_find_fresh_news_returns_empty_list_on_empty_response() -> None:
    client = AIClient(settings=make_settings(), http_client=FakeHTTPClient([""]))

    assert client.find_fresh_news() == []


def test_find_fresh_news_returns_empty_list_on_invalid_json() -> None:
    client = AIClient(settings=make_settings(), http_client=FakeHTTPClient(["not json"]))

    assert client.find_fresh_news() == []


def test_generate_image_returns_none_when_disabled() -> None:
    http_client = FakeHTTPClient([])
    client = AIClient(settings=make_settings(enable_image_generation=False), http_client=http_client)
    post = GeneratedPost(
        title="AI release",
        text="Fresh Telegram-ready post",
        image_prompt="Editorial illustration",
        source_url="https://example.com/ai-release",
    )

    assert client.generate_image(post) is None
    assert http_client.requests == []


def test_generate_image_parses_url_asset() -> None:
    content = json.dumps(
        {
            "url": "https://example.com/image.png",
            "mime_type": "image/png",
        }
    )
    http_client = FakeHTTPClient([content])
    client = AIClient(settings=make_settings(enable_image_generation=True), http_client=http_client)
    post = GeneratedPost(
        title="AI release",
        text="Fresh Telegram-ready post",
        image_prompt="Editorial illustration",
        source_url="https://example.com/ai-release",
    )

    image = client.generate_image(post)

    assert image is not None
    assert str(image.url) == "https://example.com/image.png"
    assert image.mime_type == "image/png"
    assert len(http_client.requests) == 1
