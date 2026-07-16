"""Shared Pydantic schemas for the publication workflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, model_validator


class PostStatus(str, Enum):
    """Publication lifecycle status."""

    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class News(BaseModel):
    """A candidate news item for publication."""

    title: str = Field(..., min_length=1)
    source_url: HttpUrl
    source_name: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    published_at: datetime | None = None


class GeneratedPost(BaseModel):
    """Generated Telegram post text and image prompt."""

    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    image_prompt: str = Field(default="")
    source_url: HttpUrl


class ImageAsset(BaseModel):
    """Generated image represented by bytes, URL, or local file path."""

    data: bytes | None = None
    url: HttpUrl | None = None
    file_path: str | None = None
    mime_type: str = "image/png"

    @model_validator(mode="after")
    def require_image_reference(self) -> "ImageAsset":
        if not self.data and not self.url and not self.file_path:
            raise ValueError("ImageAsset must contain data, url, or file_path")
        return self


class PublishedPost(BaseModel):
    """A persisted publication record."""

    id: int | None = None
    source_url: HttpUrl
    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    status: PostStatus
    telegram_message_id: int | None = None
    error_message: str | None = None
