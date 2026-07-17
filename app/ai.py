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
from app.schemas import ContentPlan, GeneratedPost, ImageAsset, News

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


class ContentPlanResponse(BaseModel):
    """Structured response expected for content-plan generation."""

    plan: ContentPlan


class OpenRouterImageItem(BaseModel):
    """Single item returned by OpenRouter's dedicated Image API."""

    b64_json: str | None = None
    url: str | None = None
    media_type: str | None = None


class OpenRouterImageResponse(BaseModel):
    """Buffered response from OpenRouter's dedicated Image API."""

    data: list[OpenRouterImageItem] = Field(default_factory=list)


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

    def generate_content_plan(self, description: str) -> ContentPlan:
        """Turn a free-form user request into a structured content plan."""

        if not description.strip():
            raise ValueError("Content plan description must not be empty")
        logger.info("Requesting content plan generation from OpenRouter")
        payload = self._chat_json(
            system_prompt=self._content_plan_system_prompt(),
            user_prompt=self._content_plan_user_prompt(description),
            schema=ContentPlanResponse.model_json_schema(),
            schema_name="content_plan",
        )
        try:
            response = ContentPlanResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError("OpenRouter returned an invalid content plan payload") from exc
        return response.plan.model_copy(update={"raw_request": description})

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None:
        """Generate an image asset through OpenRouter's dedicated Image API."""

        if not self.settings.enable_image_generation:
            logger.info("Image generation is disabled by ENABLE_IMAGE_GENERATION=false")
            return None

        logger.info(
            "Requesting image generation from OpenRouter Image API: endpoint=%s model=%s source_url=%s",
            self.settings.image_generation_url,
            self.settings.openrouter_image_model,
            post.source_url,
        )
        payload = self._post_image_generation(post)
        try:
            image_response = OpenRouterImageResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError("OpenRouter returned an invalid image generation payload") from exc

        if not image_response.data:
            logger.warning("OpenRouter Image API returned no image data for source_url=%s", post.source_url)
            return None

        item = image_response.data[0]
        image_data = self._decode_image_data(item.b64_json)
        if image_data is None and item.url is None:
            logger.warning("OpenRouter Image API returned an empty image item for source_url=%s", post.source_url)
            return None

        return ImageAsset(
            data=image_data,
            url=item.url,
            mime_type=item.media_type or self._mime_type_from_format(self.settings.openrouter_image_format),
        )

    def _post_image_generation(self, post: GeneratedPost) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise OpenRouterRequestError("OPENROUTER_API_KEY is required for OpenRouter image requests")

        request_payload = {
            "model": self.settings.openrouter_image_model,
            "prompt": self._image_prompt(post),
            "n": 1,
        }
        if self.settings.openrouter_image_quality:
            request_payload["quality"] = self.settings.openrouter_image_quality
        if self.settings.openrouter_image_size:
            request_payload["size"] = self.settings.openrouter_image_size
        if self.settings.openrouter_image_format:
            request_payload["output_format"] = self.settings.openrouter_image_format
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self.http_client.post(self.settings.image_generation_url, json=request_payload, headers=headers)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = response.json() if hasattr(response, "json") else response
        except Exception as exc:  # noqa: BLE001 - normalize third-party/client errors for callers
            logger.warning(
                "OpenRouter image generation request failed: endpoint=%s model=%s error=%s",
                self.settings.image_generation_url,
                self.settings.openrouter_image_model,
                exc,
            )
            raise OpenRouterRequestError("OpenRouter image generation request failed") from exc

        if not isinstance(data, dict):
            raise OpenRouterResponseError("OpenRouter image generation response must be a JSON object")
        logger.info("OpenRouter image generation completed successfully")
        return data

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

    def _content_plan_system_prompt(self) -> str:
        return "Return only JSON. You are a Telegram channel editor planning scheduled posts."

    def _content_plan_user_prompt(self, description: str) -> str:
        return (
            f"Convert this free-form content plan request into a structured plan in {self.settings.post_language}. "
            "Choose explicit ISO-8601 scheduled_at timestamps for every item, keep posts Telegram-ready, "
            "and return JSON object with key 'plan'. Plan fields: title, period_start, period_end, items. "
            "Each item fields: scheduled_at, title, text, image_prompt, optional source_url. "
            f"User request: {description}"
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

    @staticmethod
    def _image_prompt(post: GeneratedPost) -> str:
        return (
            "Safe editorial illustration for a Telegram technology news post. "
            f"Title: {post.title}. Text summary: {post.text}. Visual direction: {post.image_prompt}. "
            "No logos, no copyrighted characters, no readable UI text, no fake screenshots."
        )

    @staticmethod
    def _mime_type_from_format(value: str | None) -> str:
        if value is None:
            return "image/png"
        normalized = value.strip().lower().lstrip(".")
        if normalized in {"jpg", "jpeg"}:
            return "image/jpeg"
        if normalized == "webp":
            return "image/webp"
        if normalized == "svg":
            return "image/svg+xml"
        return "image/png"
