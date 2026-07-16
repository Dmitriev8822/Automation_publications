"""Shared Pydantic contracts used by all application modules."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class PostStatus(str, Enum):
    """Lifecycle status of a generated Telegram post."""

    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class News(BaseModel):
    """Fresh news item selected as a source for a Telegram post."""

    title: str = Field(min_length=1)
    source_url: AnyUrl
    source_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    published_at: datetime | None = None


class GeneratedPost(BaseModel):
    """Telegram-ready post generated from a news item."""

    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    image_prompt: str = ""
    source_url: AnyUrl

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Post text must not be blank")
        return value


class ImageAsset(BaseModel):
    """Generated image represented as bytes, URL, or local file path."""

    data: bytes | None = None
    url: AnyUrl | None = None
    file_path: Path | None = None
    mime_type: str = "image/png"

    @model_validator(mode="after")
    def must_have_image_source(self) -> "ImageAsset":
        if self.data is None and self.url is None and self.file_path is None:
            raise ValueError("ImageAsset must contain data, url, or file_path")
        return self


class PublishedPost(BaseModel):
    """Publication result stored in the database and returned by the service."""

    model_config = ConfigDict(use_enum_values=False)

    id: int | None = None
    source_url: AnyUrl
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    status: PostStatus
    telegram_message_id: int | None = None
    error_message: str | None = None
