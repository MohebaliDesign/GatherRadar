from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EventStatus(StrEnum):
    UPCOMING = "upcoming"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    title: str
    canonical_source_url: str
    first_seen_at: datetime
    last_seen_at: datetime
    status: EventStatus = EventStatus.UNKNOWN
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    summary: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()
    source_date_text: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str = "Asia/Tehran"
    venue_name: str | None = None
    address: str | None = None
    city: str | None = None
    event_format: str | None = None
    price_text: str | None = None
    price_amount: int | None = None
    currency: str | None = None
    registration_url: str | None = None
    language: str | None = None
    extraction_confidence: float | None = None
    source_item_ids: tuple[str, ...] = ()
    duplicate_group_id: str | None = None
    reviewer_notes: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.title.strip() or not self.canonical_source_url.strip():
            raise ValueError("event_id, title, and canonical_source_url must not be empty")
        if self.extraction_confidence is not None and not 0 <= self.extraction_confidence <= 1:
            raise ValueError("extraction_confidence must be between 0 and 1")
