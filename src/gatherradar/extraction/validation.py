from __future__ import annotations

import math
from dataclasses import fields, replace
from urllib.parse import urlparse

from .base import InvalidExtractionOutputError
from .models import EVENT_FORMATS, ExtractedEventFacts

_TEXT_FIELDS = tuple(
    field.name
    for field in fields(ExtractedEventFacts)
    if field.name not in ("is_event", "extraction_confidence")
)


def validate_extracted_facts(facts: object) -> ExtractedEventFacts:
    """Check provider output against the contract.

    Blank or whitespace-only text becomes None; non-blank text is kept exactly as given.
    Anything else that is materially invalid raises InvalidExtractionOutputError rather
    than being corrected.
    """
    if not isinstance(facts, ExtractedEventFacts):
        raise InvalidExtractionOutputError(
            f"provider returned {type(facts).__name__}, expected ExtractedEventFacts"
        )
    if not isinstance(facts.is_event, bool):
        raise InvalidExtractionOutputError("is_event must be a boolean")

    cleaned: dict[str, object] = {}
    for name in _TEXT_FIELDS:
        value = getattr(facts, name)
        if value is not None and not isinstance(value, str):
            raise InvalidExtractionOutputError(f"{name} must be text or null")
        cleaned[name] = value if value is not None and value.strip() else None

    confidence = facts.extraction_confidence
    if confidence is not None:
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise InvalidExtractionOutputError("extraction_confidence must be a number between 0 and 1")
        cleaned["extraction_confidence"] = float(confidence)

    event_format = cleaned["event_format"]
    if event_format is not None and event_format not in EVENT_FORMATS:
        raise InvalidExtractionOutputError("event_format must be in_person, online, hybrid, or null")

    registration_url = cleaned["registration_url"]
    if registration_url is not None:
        parsed = urlparse(registration_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise InvalidExtractionOutputError("registration_url must be an http or https URL")

    return replace(facts, **cleaned)
