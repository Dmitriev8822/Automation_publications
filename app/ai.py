"""OpenRouter-backed AI client for news and Telegram post generation."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.schemas import ContentPlan, ContentPlanItem, GeneratedPost, ImageAsset, News

logger = logging.getLogger(__name__)

NEWS_POST_TEMPLATE_PROMPT = """
Editorial style template for generated news posts:
- Write in Russian unless POST_LANGUAGE says otherwise.
- Keep the tone clear, lively and neutral-informative; avoid clickbait, bureaucracy and unsupported conclusions.
- Preserve factual accuracy: use only facts from the supplied news item and do not invent dates, sources or reactions.
- Use a stable Telegram structure without visible section labels: short title, 1-2 sentence lead, 2-4 compact paragraphs with key details, optional context and one concise closing sentence.
- Keep wording varied between posts: do not start every post the same way, vary sentence rhythm and vocabulary while preserving the channel style.
- Respect source-link and hashtag flags exactly.
- Avoid these filler phrases: "важно отметить", "стоит подчеркнуть", "данная ситуация", "на сегодняшний день".
""".strip()


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


class ContentPlanItemTextResponse(BaseModel):
    """Structured response expected for content-plan item text regeneration."""

    title: str
    text: str
    image_prompt: str = ""


class ContentPlanItemImagePromptResponse(BaseModel):
    """Structured response expected for content-plan item image-prompt regeneration."""

    image_prompt: str


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

    def __init__(
        self, settings: Settings | None = None, http_client: HTTPClient | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.last_error_message: str | None = None
        self.last_image_error_message: str | None = None
        if http_client is not None:
            self.http_client = http_client
        else:
            try:
                import httpx
            except ModuleNotFoundError as exc:
                raise OpenRouterRequestError(
                    "httpx is required when no custom HTTP client is provided"
                ) from exc
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
                use_web_search=self.settings.openrouter_enable_web_search,
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
            raise OpenRouterResponseError(
                "OpenRouter returned an invalid post payload"
            ) from exc

        if len(post.text) > self.settings.post_max_length:
            post = post.model_copy(
                update={"text": post.text[: self.settings.post_max_length].rstrip()}
            )
        return post

    def generate_content_plan(
        self, description: str, dialog_context: list[str] | None = None
    ) -> ContentPlan:
        """Turn a free-form user request and optional dialog context into a structured content plan."""

        if not description.strip():
            raise ValueError("Content plan description must not be empty")
        logger.info("Requesting content plan generation from OpenRouter")
        payload = self._chat_json(
            system_prompt=self._content_plan_system_prompt(),
            user_prompt=self._content_plan_user_prompt(description, dialog_context),
            schema=ContentPlanResponse.model_json_schema(),
            schema_name="content_plan",
        )
        try:
            response = ContentPlanResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError(
                "OpenRouter returned an invalid content plan payload"
            ) from exc
        plan = self._normalize_content_plan_datetimes(response.plan)
        return plan.model_copy(update={"raw_request": description})

    def regenerate_content_plan_item_text(
        self, item: ContentPlanItem, instruction: str = ""
    ) -> ContentPlanItem:
        """Regenerate text and image prompt for a scheduled content-plan item."""

        prompt = (
            f"Rewrite this Telegram post in {self.settings.post_language}. "
            f"Keep the scheduled time {item.scheduled_at.isoformat()}. "
            f"User instruction: {instruction or 'improve the post while preserving the topic'}. "
            f"Current title: {item.title}. Current text: {item.text}. Current image prompt: {item.image_prompt}. "
            "Return JSON with title, text and image_prompt."
        )
        payload = self._chat_json(
            system_prompt="Return only JSON. You rewrite approved Telegram content-plan posts.",
            user_prompt=prompt,
            schema=ContentPlanItemTextResponse.model_json_schema(),
            schema_name="content_plan_item_text",
        )
        try:
            response = ContentPlanItemTextResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError(
                "OpenRouter returned an invalid regenerated content-plan item"
            ) from exc
        return item.model_copy(
            update={
                "title": response.title,
                "text": response.text,
                "image_prompt": response.image_prompt,
            }
        )

    def regenerate_content_plan_item_image_prompt(
        self, item: ContentPlanItem, instruction: str = ""
    ) -> ContentPlanItem:
        """Regenerate only the image prompt for a scheduled content-plan item."""

        prompt = (
            f"Create a new image prompt for this Telegram post. User instruction: {instruction or 'make it clearer and more vivid'}. "
            f"Title: {item.title}. Text: {item.text}. Current image prompt: {item.image_prompt}. "
            "Return JSON with image_prompt."
        )
        payload = self._chat_json(
            system_prompt="Return only JSON. You create safe editorial image prompts for Telegram posts.",
            user_prompt=prompt,
            schema=ContentPlanItemImagePromptResponse.model_json_schema(),
            schema_name="content_plan_item_image_prompt",
        )
        try:
            response = ContentPlanItemImagePromptResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenRouterResponseError(
                "OpenRouter returned an invalid regenerated image prompt"
            ) from exc
        return item.model_copy(update={"image_prompt": response.image_prompt})

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None:
        """Generate an image asset through OpenRouter's dedicated Image API."""

        self.last_image_error_message = None
        if not self.settings.enable_image_generation:
            self.last_image_error_message = "ENABLE_IMAGE_GENERATION=false"
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
            raise OpenRouterResponseError(
                "OpenRouter returned an invalid image generation payload"
            ) from exc

        if not image_response.data:
            self.last_image_error_message = "OpenRouter Image API returned no image data"
            logger.warning(
                "OpenRouter Image API returned no image data for source_url=%s",
                post.source_url,
            )
            return None

        item = image_response.data[0]
        image_data = self._decode_image_data(item.b64_json)
        if image_data is None and item.url is None:
            self.last_image_error_message = "OpenRouter Image API returned an empty image item"
            logger.warning(
                "OpenRouter Image API returned an empty image item for source_url=%s",
                post.source_url,
            )
            return None

        return ImageAsset(
            data=image_data,
            url=item.url,
            mime_type=item.media_type
            or self._mime_type_from_format(self.settings.openrouter_image_format),
        )

    def _post_image_generation(self, post: GeneratedPost) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise OpenRouterRequestError(
                "OPENROUTER_API_KEY is required for OpenRouter image requests"
            )

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
            response = self.http_client.post(
                self.settings.image_generation_url,
                json=request_payload,
                headers=headers,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = response.json() if hasattr(response, "json") else response
        except (
            Exception
        ) as exc:  # noqa: BLE001 - normalize third-party/client errors for callers
            logger.warning(
                "OpenRouter image generation request failed: endpoint=%s model=%s error=%s",
                self.settings.image_generation_url,
                self.settings.openrouter_image_model,
                exc,
            )
            raise OpenRouterRequestError(
                "OpenRouter image generation request failed"
            ) from exc

        if not isinstance(data, dict):
            raise OpenRouterResponseError(
                "OpenRouter image generation response must be a JSON object"
            )
        logger.info("OpenRouter image generation completed successfully")
        return data

    def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        use_web_search: bool = False,
    ) -> dict[str, Any]:
        response = self._post_chat_completion(
            system_prompt, user_prompt, schema, schema_name, use_web_search
        )
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

    def _post_chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        use_web_search: bool = False,
    ) -> dict[str, Any]:
        if not self.settings.openrouter_api_key:
            raise OpenRouterRequestError(
                "OPENROUTER_API_KEY is required for OpenRouter requests"
            )

        model = self._chat_model_name()
        logger.info(
            "Sending OpenRouter chat completion request: endpoint=%s model=%s schema=%s",
            self.settings.chat_completions_url,
            model,
            schema_name,
        )
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        if use_web_search:
            request_payload["tools"] = [self._web_search_tool()]
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        try:
            data = self._send_chat_completion_request(
                request_payload, headers, schema_name
            )
        except OpenRouterRequestError:
            logger.warning(
                "Retrying OpenRouter request with json_object response format: model=%s schema=%s",
                model,
                schema_name,
            )
            fallback_payload = dict(request_payload)
            fallback_payload["response_format"] = {"type": "json_object"}
            data = self._send_chat_completion_request(
                fallback_payload, headers, schema_name
            )

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
            response = self.http_client.post(
                self.settings.chat_completions_url,
                json=request_payload,
                headers=headers,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            return response.json() if hasattr(response, "json") else response
        except (
            Exception
        ) as exc:  # noqa: BLE001 - normalize third-party/client errors for callers
            logger.warning(
                "OpenRouter request failed: endpoint=%s model=%s schema=%s error=%s",
                self.settings.chat_completions_url,
                request_payload.get("model", self.settings.openrouter_model),
                schema_name,
                exc,
            )
            raise OpenRouterRequestError(self._format_request_error(exc)) from exc

    def _chat_model_name(self) -> str:
        """Return the configured model name for Chat Completions requests.

        OpenRouter supports model suffixes such as ``:online`` for models that
        should use online/search-grounded behavior. The client must preserve the
        configured suffix instead of normalizing it away, otherwise a news lookup
        can silently fall back to the ordinary offline model.
        """

        return self.settings.openrouter_model.strip()

    @staticmethod
    def _format_request_error(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        reason = getattr(response, "reason_phrase", None)
        if status_code is None:
            return f"OpenRouter request failed: {exc}"

        detail = ""
        if response is not None:
            try:
                body = response.json()
            except Exception:  # noqa: BLE001 - best-effort diagnostic only
                body = getattr(response, "text", "")
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                else:
                    detail = str(body.get("message") or body)
            elif body:
                detail = str(body)
        message = f"OpenRouter request failed with HTTP {status_code}"
        if reason:
            message += f" {reason}"
        if detail:
            message += f": {detail[:500]}"
        return message

    def _web_search_tool(self) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "max_results": self.settings.openrouter_web_search_max_results
        }
        if self.settings.openrouter_web_search_engine:
            parameters["engine"] = self.settings.openrouter_web_search_engine
        return {"type": "openrouter:web_search", "parameters": parameters}

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> Any:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenRouterResponseError(
                "OpenRouter response does not contain choices"
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise OpenRouterResponseError(
                "OpenRouter response does not contain a message"
            )
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
                raise OpenRouterResponseError(
                    "OpenRouter returned an invalid data URL for image"
                )
        try:
            return base64.b64decode(image_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OpenRouterResponseError(
                "OpenRouter image data must be base64-encoded bytes"
            ) from exc

    def _news_system_prompt(self) -> str:
        return "Return only JSON. You are a news editor selecting fresh, reliable and publication-ready news."

    def _news_user_prompt(self) -> str:
        return (
            f"Find up to {self.settings.max_news_items} fresh news items about '{self.settings.news_topic}' using web search. "
            f"Language for news summaries: {self.settings.news_language}. Prioritize relevance and recency. "
            "Use only web-search-backed sources with real public URLs; do not invent sources, dates or links. "
            "Return JSON object with key 'news'. Each item must include title, source_url, source_name, summary, "
            "and optional ISO-8601 published_at."
        )

    def _content_plan_system_prompt(self) -> str:
        return "Return only JSON. You are a Telegram channel editor planning scheduled posts."

    def _content_plan_user_prompt(
        self, description: str, dialog_context: list[str] | None = None
    ) -> str:
        now = datetime.now(self.settings.timezone)
        context = "\n".join(dialog_context or [])
        context_part = (
            f" Conversation context and revisions: {context}." if context else ""
        )
        return (
            f"Convert this free-form content plan request into a structured plan in {self.settings.post_language}. "
            f"Current application time is {now.isoformat()} in timezone {self.settings.app_timezone}. "
            f"Interpret user times without an explicit timezone as {self.settings.app_timezone}. "
            "Choose explicit ISO-8601 scheduled_at timestamps with UTC offset for every item, keep posts Telegram-ready, "
            "and return JSON object with key 'plan'. Plan fields: title, period_start, period_end, items. "
            "Each item fields: scheduled_at, title, text, image_prompt, optional source_url. "
            f"User request: {description}."
            f"{context_part}"
        )

    def _normalize_content_plan_datetimes(self, plan: ContentPlan) -> ContentPlan:
        """Normalize AI-produced naive datetimes to the configured app timezone."""

        timezone_info = self.settings.timezone

        def normalize(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone_info)
            return value.astimezone(timezone_info)

        return plan.model_copy(
            update={
                "period_start": normalize(plan.period_start),
                "period_end": normalize(plan.period_end),
                "items": [
                    item.model_copy(
                        update={"scheduled_at": normalize(item.scheduled_at)}
                    )
                    for item in plan.items
                ],
            }
        )

    def _post_system_prompt(self) -> str:
        return (
            "Return only JSON. You write Telegram news posts from validated news. "
            "Always follow the editorial style template from the user prompt."
        )

    def _post_user_prompt(self, news: News) -> str:
        return (
            f"Create a Telegram post in {self.settings.post_language}. Style setting: {self.settings.post_style}. "
            f"Maximum length: {self.settings.post_max_length} characters. "
            f"Include source link: {self.settings.include_source_link}. Include hashtags: {self.settings.include_hashtags}. "
            f"Apply this style template: {NEWS_POST_TEMPLATE_PROMPT} "
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
