from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .source import SourceType


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RawItem:
    id: str
    source_id: str
    source_type: SourceType
    external_id: str
    content_type: str
    content_url: str
    raw_text: str
    captured_at: datetime
    published_at: datetime | None = None
    author: str | None = None
    image_url: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "source_id", "external_id", "content_type", "content_url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        _require_aware(self.captured_at, "captured_at")
        _require_aware(self.published_at, "published_at")
