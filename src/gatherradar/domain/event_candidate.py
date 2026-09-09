from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventCandidate:
    candidate_id: str
    raw_item_id: str
    is_event: bool
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    source_date_text: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
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
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.raw_item_id.strip():
            raise ValueError("candidate_id and raw_item_id must not be empty")
        if self.extraction_confidence is not None and not 0 <= self.extraction_confidence <= 1:
            raise ValueError("extraction_confidence must be between 0 and 1")
