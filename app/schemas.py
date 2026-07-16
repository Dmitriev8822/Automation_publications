"""Shared Pydantic schemas used across application modules."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class PostStatus(str, Enum):
    """Lifecycle statuses for generated and published posts."""

    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class News(BaseModel):
    """News item selected as a source for a Telegram publication."""

    title: str
    source_url: AnyUrl
    source_name: str
    summary: str
    published_at: datetime | None = None


class GeneratedPost(BaseModel):
    """Post text and image prompt generated from a news item."""

    title: str
    text: str = Field(..., min_length=1)
    image_prompt: str
    source_url: AnyUrl

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        """Require meaningful non-whitespace post text."""
        if not value.strip():
            raise ValueError("GeneratedPost text must not be empty")
        return value


class ImageAsset(BaseModel):
    """Image payload or reference prepared for Telegram publication."""

    data: bytes | None = None
    url: AnyUrl | None = None
    file_path: str | None = None
    mime_type: str = "image/png"

    @model_validator(mode="after")
    def require_image_source(self) -> "ImageAsset":
        """Require at least one concrete source for the image."""
        if self.data is None and self.url is None and self.file_path is None:
            raise ValueError("ImageAsset must contain data, url, or file_path")
        return self


class PublishedPost(BaseModel):
    """Publication record shared between service, Telegram, and database modules."""

    model_config = ConfigDict(use_enum_values=False)

    id: int | None = None
    source_url: AnyUrl
    title: str
    text: str
    status: PostStatus
    telegram_message_id: int | None = None
    error_message: str | None = None
