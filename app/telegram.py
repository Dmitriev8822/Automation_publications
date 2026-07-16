"""Telegram publishing interfaces and placeholder implementation."""

from __future__ import annotations

from app.config import Settings
from app.schemas import GeneratedPost, ImageAsset


class TelegramPublisher:
    """Interface for publishing generated posts to Telegram."""

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        raise NotImplementedError


class TeleBotPublisher(TelegramPublisher):
    """pyTelegramBotAPI adapter scaffold."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def publish_post(self, post: GeneratedPost, image: ImageAsset | None = None) -> int:
        raise NotImplementedError("Telegram publishing is not implemented yet")
