from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, model_validator


class PostStatus(str, Enum):
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class News(BaseModel):
    title: str
    source_url: HttpUrl
    source_name: str
    summary: str
    published_at: datetime | None = None


class GeneratedPost(BaseModel):
    title: str
    text: str = Field(min_length=1)
    image_prompt: str = ""
    source_url: str


class ImageAsset(BaseModel):
    data: bytes | None = None
    url: str | None = None
    file_path: str | None = None
    mime_type: str = "image/png"

    @model_validator(mode="after")
    def require_image_source(self) -> "ImageAsset":
        if self.data is None and self.url is None and self.file_path is None:
            raise ValueError("ImageAsset must contain data, url, or file_path")
        return self


class PublishedPost(BaseModel):
    id: int | None = None
    source_url: str
    title: str
    text: str
    status: PostStatus
    telegram_message_id: int | None = None
    error_message: str | None = None
