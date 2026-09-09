from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class SourceType(StrEnum):
    INSTAGRAM = "instagram"
    WEBSITE = "website"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    publisher_key: str
    name: str
    source_type: SourceType
    url: str
    enabled: bool = True
    username: str | None = None
    city_hint: str | None = None
    timezone: str = "Asia/Tehran"
    locale: str = "fa-IR"

    def __post_init__(self) -> None:
        for field_name in ("id", "publisher_key", "name", "url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")

        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")

        if self.source_type is SourceType.INSTAGRAM and not self.username:
            raise ValueError("Instagram sources require a username")
