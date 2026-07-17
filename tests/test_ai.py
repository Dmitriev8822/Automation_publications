"""Tests for OpenRouter AI client without real API calls."""

from __future__ import annotations

import base64
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


class FailingHTTPClient:
    def post(self, url: str, **kwargs):
        raise RuntimeError("401 Unauthorized")


class FakeHTTPStatusResponse:
    status_code = 403
    reason_phrase = "Forbidden"

    def json(self) -> dict:
        return {"error": {"message": "model access denied"}}


class FakeHTTPStatusError(Exception):
    def __init__(self) -> None:
        super().__init__("Client error '403 Forbidden'")
        self.response = FakeHTTPStatusResponse()


class FailingHTTPStatusClient:
    def post(self, url: str, **kwargs):
        raise FakeHTTPStatusError()


class FakeHTTPClient:
    def __init__(self, contents: list[object]) -> None:
        self.contents = contents
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        content = self.contents.pop(0)
        if isinstance(content, dict) and "data" in content:
            return FakeResponse(content)
        return FakeResponse({"choices": [{"message": {"content": content}}]})


class FailingThenSuccessfulHTTPClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[dict] = []

    def post(self, url: str, **kwargs):
        self.requests.append({"url": url, **kwargs})
        if len(self.requests) == 1:
            raise RuntimeError("400 Bad Request")
        return FakeResponse({"choices": [{"message": {"content": self.content}}]})


def make_settings(**overrides) -> Settings:
    defaults = {
        "openrouter_api_key": "test-key",
        "max_news_items": 2,
        "enable_image_generation": True,
    }
    defaults.update(overrides)
    return Settings(**defaults, _env_file=None)


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


def test_find_fresh_news_uses_openrouter_web_search_tool() -> None:
    content = json.dumps({"news": []})
    http_client = FakeHTTPClient([content])
    client = AIClient(
        settings=make_settings(
            openrouter_enable_web_search=True,
            openrouter_web_search_engine="native",
            openrouter_web_search_max_results=3,
        ),
        http_client=http_client,
    )

    assert client.find_fresh_news() == []

    payload = http_client.requests[0]["json"]
    assert payload["tools"] == [
        {
            "type": "openrouter:web_search",
            "parameters": {"max_results": 3, "engine": "native"},
        }
    ]
    assert "using web search" in payload["messages"][1]["content"]


def test_generate_post_does_not_use_web_search_tool() -> None:
    content = json.dumps(
        {
            "title": "AI release",
            "text": "Fresh Telegram-ready post",
            "image_prompt": "Editorial illustration of AI automation",
            "source_url": "https://example.com/ai-release",
        }
    )
    http_client = FakeHTTPClient([content])
    client = AIClient(settings=make_settings(openrouter_enable_web_search=True), http_client=http_client)
    news = News(
        title="AI release",
        source_url="https://example.com/ai-release",
        source_name="Example",
        summary="A new AI system was released.",
    )

    client.generate_post(news)

    assert "tools" not in http_client.requests[0]["json"]


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
    content = {
        "data": [
            {
                "url": "https://example.com/image.png",
                "media_type": "image/png",
            }
        ]
    }
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
    assert http_client.requests[0]["url"].endswith("/images")
    assert http_client.requests[0]["json"]["model"] == "openai/gpt-image-1-mini"
    assert http_client.requests[0]["json"]["quality"] == "low"
    assert "size" not in http_client.requests[0]["json"]


def test_generate_image_decodes_base64_asset() -> None:
    encoded = base64.b64encode(b"image-bytes").decode("ascii")
    content = {
        "data": [
            {
                "b64_json": encoded,
                "media_type": "image/png",
            }
        ]
    }
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
    assert image.data == b"image-bytes"
    assert image.mime_type == "image/png"


def test_generate_image_ignores_nonexistent_file_path_asset() -> None:
    content = json.dumps(
        {
            "file_path": "assets/missing-generated-image.jpg",
            "mime_type": "image/jpeg",
        }
    )
    client = AIClient(settings=make_settings(enable_image_generation=True), http_client=FakeHTTPClient([content]))
    post = GeneratedPost(
        title="AI release",
        text="Fresh Telegram-ready post",
        image_prompt="Editorial illustration",
        source_url="https://example.com/ai-release",
    )

    assert client.generate_image(post) is None


def test_generate_image_decodes_data_url_asset() -> None:
    encoded = base64.b64encode(b"png-bytes").decode("ascii")
    content = {
        "data": [
            {
                "b64_json": f"data:image/png;base64,{encoded}",
                "media_type": "image/png",
            }
        ]
    }
    client = AIClient(settings=make_settings(enable_image_generation=True), http_client=FakeHTTPClient([content]))
    post = GeneratedPost(
        title="AI release",
        text="Fresh Telegram-ready post",
        image_prompt="Editorial illustration",
        source_url="https://example.com/ai-release",
    )

    image = client.generate_image(post)

    assert image is not None
    assert image.data == b"png-bytes"


def test_find_fresh_news_stores_error_message_on_request_failure() -> None:
    client = AIClient(settings=make_settings(), http_client=FailingHTTPClient())

    assert client.find_fresh_news() == []
    assert client.last_error_message == "OpenRouter request failed: 401 Unauthorized"


def test_find_fresh_news_stores_status_and_body_on_http_status_failure() -> None:
    client = AIClient(settings=make_settings(), http_client=FailingHTTPStatusClient())

    assert client.find_fresh_news() == []
    assert client.last_error_message == "OpenRouter request failed with HTTP 403 Forbidden: model access denied"


def test_chat_requests_strip_legacy_online_model_suffix() -> None:
    content = json.dumps(
        {
            "title": "AI release",
            "text": "Fresh Telegram-ready post",
            "image_prompt": "Editorial illustration of AI automation",
            "source_url": "https://example.com/ai-release",
        }
    )
    http_client = FakeHTTPClient([content])
    client = AIClient(
        settings=make_settings(openrouter_model="openai/gpt-4.1-mini:online"),
        http_client=http_client,
    )
    news = News(
        title="AI release",
        source_url="https://example.com/ai-release",
        source_name="Example",
        summary="A new AI system was released.",
    )

    client.generate_post(news)

    assert http_client.requests[0]["json"]["model"] == "openai/gpt-4.1-mini"


def test_find_fresh_news_retries_with_json_object_when_json_schema_request_fails() -> None:
    content = json.dumps(
        {
            "news": [
                {
                    "title": "New model",
                    "source_url": "https://example.com/new-model",
                    "source_name": "Example",
                    "summary": "A newer model became available.",
                }
            ]
        }
    )
    http_client = FailingThenSuccessfulHTTPClient(content)
    client = AIClient(settings=make_settings(), http_client=http_client)

    news = client.find_fresh_news()

    assert len(news) == 1
    assert news[0].title == "New model"
    assert len(http_client.requests) == 2
    assert http_client.requests[0]["json"]["response_format"]["type"] == "json_schema"
    assert http_client.requests[1]["json"]["response_format"]["type"] == "json_object"


def test_generate_content_plan_parses_structured_plan() -> None:
    content = json.dumps(
        {
            "plan": {
                "title": "План на неделю",
                "period_start": "2026-07-20T09:00:00",
                "period_end": "2026-07-26T18:00:00",
                "items": [
                    {
                        "scheduled_at": "2026-07-20T10:00:00",
                        "title": "Первый пост",
                        "text": "Текст первого поста",
                        "image_prompt": "Иллюстрация",
                    }
                ],
            }
        }
    )
    client = AIClient(settings=make_settings(), http_client=FakeHTTPClient([content]))

    plan = client.generate_content_plan("нужен план на неделю")

    assert plan.title == "План на неделю"
    assert plan.raw_request == "нужен план на неделю"
    assert plan.items[0].title == "Первый пост"
    assert plan.items[0].scheduled_at.tzinfo is not None
    assert plan.items[0].scheduled_at.isoformat() == "2026-07-20T10:00:00+03:00"
    assert client.http_client.requests[0]["json"]["response_format"]["json_schema"]["name"] == "content_plan"
    assert "Europe/Moscow" in client.http_client.requests[0]["json"]["messages"][1]["content"]
