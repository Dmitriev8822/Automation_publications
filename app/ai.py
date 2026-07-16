"""OpenRouter-backed AI client for news and Telegram post generation."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.schemas import GeneratedPost, ImageAsset, News

logger = logging.getLogger(__name__)


class AIClientError(RuntimeError):
    """Base exception for AI client errors."""


class OpenRouterRequestError(AIClientError):
    """Raised when OpenRouter rejects a request or is unavailable."""


class OpenRouterResponseError(AIClientError):
    """Raised when OpenRouter returns data that cannot be parsed."""


class HTTPClient(Protocol):
    """Minimal HTTP client protocol used by AIClient."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


class NewsListResponse(BaseModel):
    """Structured response expected for fresh-news lookup."""

    news: list[News] = Field(default_factory=list)


class ImageResponse(BaseModel):
    """Structured response expected for image generation."""

    data: str | None = None
    base64_data: str | None = None
    url: str | None = None
    file_path: str | None = None
    mime_type: str = "image/png"


class AIClient:
    """Client that asks OpenRouter to find news and generate publication assets."""

    def __init__(self, settings: Settings | None = None, http_client: HTTPClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.last_error_message: str | None = None
        if http_client is not None:
            self.http_client = http_client
        else:
            try:
                import httpx
            except ModuleNotFoundError as exc:
                raise OpenRouterRequestError("httpx is required when no custom HTTP client is provided") from exc
            self.http_client = httpx.Client(timeout=60)

    def find_fresh_news(self) -> list[News]:
        """Return prioritized fresh news for the configured topic.

        Empty OpenRouter responses and invalid JSON are treated as safe misses and
        return an empty list, because the publishing pipeline can simply skip a run.
        """

        try:
            self.last_error_message = None
            logger.info(
                "Requesting fresh news from OpenRouter: endpoint=%s model=%s topic=%r max_items=%s api_key_configured=%s",
                self.settings.chat_completions_url,
                self.settings.openrouter_model,
                self.settings.news_topic,
                self.settings.max_news_items,
                bool(self.settings.openrouter_api_key),
            )
            payload = self._chat_json(
                system_prompt=self._news_system_prompt(),
                user_prompt=self._news_user_prompt(),
                schema=NewsListResponse.model_json_schema(),
                schema_name="fresh_news",
            )
            response = NewsListResponse.model_validate(payload)
        except (AIClientError, ValidationError, TypeError, ValueError) as exc:
            self.last_error_message = str(exc) or exc.__class__.__name__
            logger.warning("Could not fetch fresh news from OpenRouter: %s", exc)
            return []

        logger.info("OpenRouter returned %d fresh news item(s)", len(response.news))
        return response.news[: self.settings.max_news_items]

    def generate_post(self, news: News) -> GeneratedPost:
        """Generate a Telegram post from one news item."""

        logger.info(
            "Requesting Telegram post generation from OpenRouter: source_url=%s model=%s max_length=%s",
            news.source_url,
            self.settings.openrouter_model,
            self.settings.post_max_length,
        )
        payload = self._chat_json(
            system_prompt=self._post_system_prompt(),
            user_prompt=self._post_user_prompt(news),
            schema=GeneratedPost.model_json_schema(),
            schema_name="generated_post",
        )
        try:
            post = GeneratedPost.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError("OpenRouter returned an invalid post payload") from exc

        if len(post.text) > self.settings.post_max_length:
            post = post.model_copy(update={"text": post.text[: self.settings.post_max_length].rstrip()})
        return post

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None:
        """Generate an image asset, or None when image generation is disabled."""

        if not self.settings.enable_image_generation:
            logger.info("Image generation is disabled by ENABLE_IMAGE_GENERATION=false")
            return None

        logger.info("Requesting image generation from OpenRouter: source_url=%s", post.source_url)
        payload = self._chat_json(
            system_prompt=self._image_system_prompt(),
            user_prompt=self._image_user_prompt(post),
            schema=ImageResponse.model_json_schema(),
            schema_name="image_asset",
        )
        try:
            image = ImageResponse.model_validate(payload)
            return ImageAsset(
                data=self._decode_image_data(image.data or image.base64_data),
                url=image.url,
                file_path=image.file_path,
                mime_type=image.mime_type,
            )
        except ValidationError as exc:
            raise OpenRouterResponseError("OpenRouter returned an invalid image payload") from exc

    def _chat_json(self, system_prompt: str, user_prompt: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        response = self._post_chat_completion(system_prompt, user_prompt, schema, schema_name)
        content = self._extract_message_content(response)
        if isinstance(content, Mapping):
            return dict(content)
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterResponseError("OpenRouter returned an empty message")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OpenRouterResponseError("OpenRouter returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenRouterResponseError("OpenRouter JSON response must be an object")
        return parsed

    def _post_chat_completion(self, system_prompt: str, user_prompt: str, schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise OpenRouterRequestError("OPENROUTER_API_KEY is required for OpenRouter requests")

        logger.info(
            "Sending OpenRouter chat completion request: endpoint=%s model=%s schema=%s",
            self.settings.chat_completions_url,
            self.settings.openrouter_model,
            schema_name,
        )
        request_payload = {
            "model": self.settings.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        try:
            data = self._send_chat_completion_request(request_payload, headers, schema_name)
        except OpenRouterRequestError:
            logger.warning(
                "Retrying OpenRouter request with json_object response format: model=%s schema=%s",
                self.settings.openrouter_model,
                schema_name,
            )
            fallback_payload = dict(request_payload)
            fallback_payload["response_format"] = {"type": "json_object"}
            data = self._send_chat_completion_request(fallback_payload, headers, schema_name)

        if not isinstance(data, dict):
            raise OpenRouterResponseError("OpenRouter response must be a JSON object")
        logger.info("OpenRouter request completed successfully: schema=%s", schema_name)
        return data

    def _send_chat_completion_request(
        self,
        request_payload: dict[str, Any],
        headers: dict[str, str],
        schema_name: str,
    ) -> dict[str, Any]:
        try:
            response = self.http_client.post(self.settings.chat_completions_url, json=request_payload, headers=headers)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            return response.json() if hasattr(response, "json") else response
        except Exception as exc:  # noqa: BLE001 - normalize third-party/client errors for callers
            logger.warning(
                "OpenRouter request failed: endpoint=%s model=%s schema=%s error=%s",
                self.settings.chat_completions_url,
                self.settings.openrouter_model,
                schema_name,
                exc,
            )
            raise OpenRouterRequestError("OpenRouter request failed") from exc

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> Any:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenRouterResponseError("OpenRouter response does not contain choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise OpenRouterResponseError("OpenRouter response does not contain a message")
        return message.get("content")

    @staticmethod
    def _decode_image_data(value: str | None) -> bytes | None:
        if value is None:
            return None
        image_data = value.strip()
        if not image_data:
            return None
        if image_data.startswith("data:"):
            _, separator, image_data = image_data.partition(",")
            if not separator:
                raise OpenRouterResponseError("OpenRouter returned an invalid data URL for image")
        try:
            return base64.b64decode(image_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OpenRouterResponseError("OpenRouter image data must be base64-encoded bytes") from exc

    def _news_system_prompt(self) -> str:
        return "Return only JSON. You are a news editor selecting fresh, reliable and publication-ready news."

    def _news_user_prompt(self) -> str:
        return (
            f"Find up to {self.settings.max_news_items} fresh news items about '{self.settings.news_topic}'. "
            f"Language for news summaries: {self.settings.news_language}. Prioritize relevance and recency. "
            "Return JSON object with key 'news'. Each item must include title, source_url, source_name, summary, "
            "and optional ISO-8601 published_at."
        )

    def _post_system_prompt(self) -> str:
        return "Return only JSON. You write concise Telegram posts from validated news."

    def _post_user_prompt(self, news: News) -> str:
        return (
            f"Create a Telegram post in {self.settings.post_language}. Style: {self.settings.post_style}. "
            f"Maximum length: {self.settings.post_max_length} characters. "
            f"Include source link: {self.settings.include_source_link}. Include hashtags: {self.settings.include_hashtags}. "
            f"News title: {news.title}. Summary: {news.summary}. Source: {news.source_name} {news.source_url}. "
            "Return JSON with title, text, image_prompt, source_url."
        )

    def _image_system_prompt(self) -> str:
        return (
            "Return only JSON. Create a real image asset for a Telegram publication. "
            "Do not return a text-only prompt as the image."
        )

    @staticmethod
    def _image_user_prompt(post: GeneratedPost) -> str:
        return (
            f"Generate a safe editorial image asset for this post. Title: {post.title}. "
            f"Text: {post.text}. Preferred prompt: {post.image_prompt}. "
            "Return an object with either base64_data containing base64-encoded image bytes, "
            "a direct HTTPS image url, or file_path, plus mime_type. "
            "Do not return only a rewritten prompt."
        )
