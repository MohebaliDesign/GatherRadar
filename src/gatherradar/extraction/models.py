from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

EVENT_FORMATS = frozenset({"in_person", "online", "hybrid"})


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    """The deliberate, auditable evidence a provider may see for one RawItem.

    Adapter `raw_metadata` is intentionally excluded; the RawItem remains the system
    record. `locale`, `timezone`, and `city_hint` are source configuration context and
    are only set when that configuration is supplied.
    """

    raw_item_id: str
    source_id: str
    source_type: str
    raw_text: str
    content_url: str
    content_type: str
    published_at: datetime | None = None
    author: str | None = None
    locale: str | None = None
    timezone: str | None = None
    city_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedEventFacts:
    """Provider output for one RawItem: whether it announces a concrete attendable event,
    plus source-supported facts before deterministic validation and normalization.

    Every value must be traceable to the source text or supplied source context.
    Unknown values stay None; an event may legitimately have no title.
    """

    is_event: bool
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    source_date_text: str | None = None
    venue_name: str | None = None
    address: str | None = None
    city: str | None = None
    event_format: str | None = None
    price_text: str | None = None
    registration_url: str | None = None
    language: str | None = None
    extraction_confidence: float | None = None
