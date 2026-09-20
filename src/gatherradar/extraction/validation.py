from __future__ import annotations

import math
from dataclasses import fields, replace
from urllib.parse import urlparse

from ..domain import DiscoveryType
from .base import InvalidExtractionOutputError
from .models import EVENT_FORMATS, DiscoveryEvidence, DiscoveryFacts

_TEXT_FIELDS = tuple(
    field.name
    for field in fields(DiscoveryFacts)
    if field.name not in ("discovery_type", "extraction_confidence", "evidence")
)

# Fields that only make sense for one kind of result. A place has no occurrence and
# no registration; an event has no opening hours. Mixing them would let a provider
# smuggle invented facts into the wrong record.
_EVENT_ONLY_FIELDS = ("source_date_text", "event_format", "registration_url")
_PLACE_ONLY_FIELDS = ("opening_hours_text",)


def validate_discovery_facts(facts: object) -> DiscoveryFacts:
    """Check provider output against the contract.

    Blank or whitespace-only text becomes None; non-blank text is kept exactly as
    given. Anything else that is materially invalid raises
    InvalidExtractionOutputError rather than being corrected.
    """
    if not isinstance(facts, DiscoveryFacts):
        raise InvalidExtractionOutputError(
            f"provider returned {type(facts).__name__}, expected DiscoveryFacts"
        )
    if not isinstance(facts.discovery_type, DiscoveryType):
        raise InvalidExtractionOutputError("discovery_type must be a DiscoveryType")
    if facts.evidence is not None and not isinstance(facts.evidence, DiscoveryEvidence):
        raise InvalidExtractionOutputError("evidence must be DiscoveryEvidence or null")

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

    _reject_mismatched_fields(facts.discovery_type, cleaned)
    return replace(facts, **cleaned)


def _reject_mismatched_fields(discovery_type: DiscoveryType, cleaned: dict[str, object]) -> None:
    if discovery_type is DiscoveryType.OTHER:
        supplied = [name for name in _TEXT_FIELDS if cleaned[name] is not None]
        if supplied:
            raise InvalidExtractionOutputError(
                f"{discovery_type.value} carries no facts, but {', '.join(sorted(supplied))} was supplied"
            )
        return

    forbidden = _PLACE_ONLY_FIELDS if discovery_type is DiscoveryType.EVENT else _EVENT_ONLY_FIELDS
    supplied = [name for name in forbidden if cleaned[name] is not None]
    if supplied:
        raise InvalidExtractionOutputError(
            f"{', '.join(sorted(supplied))} is not a {discovery_type.value} field"
        )


__all__ = ["validate_discovery_facts"]
