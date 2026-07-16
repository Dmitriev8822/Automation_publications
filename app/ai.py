"""OpenRouter client interfaces and placeholder implementation."""

from __future__ import annotations

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset, News


class AIClient:
    """Interface for finding news and generating content via AI providers."""

    def find_fresh_news(self) -> list[News]:
        raise NotImplementedError

    def generate_post(self, news: News) -> GeneratedPost:
        raise NotImplementedError

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None:
        raise NotImplementedError


class OpenRouterAIClient(AIClient):
    """OpenRouter adapter scaffold.

    Real HTTP calls will be implemented by the AI module task. The class exists so
    other modules can depend on the stable interface immediately.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def find_fresh_news(self) -> list[News]:
        raise NotImplementedError("OpenRouter news search is not implemented yet")

    def generate_post(self, news: News) -> GeneratedPost:
        raise NotImplementedError("OpenRouter post generation is not implemented yet")

    def generate_image(self, post: GeneratedPost) -> ImageAsset | None:
        if not self.settings.enable_image_generation:
            return None
        raise NotImplementedError("OpenRouter image generation is not implemented yet")
