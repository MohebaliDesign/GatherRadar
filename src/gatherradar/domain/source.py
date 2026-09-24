from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from .website import WebsiteConfig


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
    website: WebsiteConfig | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "publisher_key", "name", "url"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")

        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        if parsed.username or parsed.password or not parsed.hostname or any(c.isspace() for c in self.url):
            raise ValueError('url must not contain credentials or whitespace')
        try:
            parsed.port
        except ValueError:
            raise ValueError('invalid URL port') from None
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.id):
            raise ValueError('source id must be safe for a storage filename')
        if not isinstance(self.enabled, bool):
            raise ValueError('enabled must be a boolean')
        if self.website is not None and (
            self.source_type is not SourceType.WEBSITE or not isinstance(self.website, WebsiteConfig)
        ):
            raise ValueError('website configuration requires a website Source')

        if self.source_type is SourceType.INSTAGRAM and not self.username:
            raise ValueError("Instagram sources require a username")
