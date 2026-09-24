from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum

from ..domain import (
    DiscoveryType, DiscoveryUnit, EventCandidate, PlaceCandidate,
    RawItem, Source,
)
from ..domain.evidence import primary_discovery_units
from .base import DiscoveryProvider, InvalidExtractionOutputError, ProviderExtractionError
from .models import DiscoveryEvidence, DiscoveryFacts, ExtractionInput
from .signals import has_meaningful_content
from .validation import validate_discovery_facts

SKIP_EMPTY_TEXT = "empty_text"
SKIP_INSUFFICIENT_TEXT = "insufficient_text"


class DiscoveryStatus(StrEnum):
    DISCOVERED = "discovered"
    SKIPPED = "skipped"
    PROVIDER_FAILED = "provider_failed"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    """Result of analyzing one RawItem.

    Operational and explanatory detail stays here, not on the candidate: `evidence`
    records why the provider decided as it did and is never persisted.
    """

    raw_item_id: str
    status: DiscoveryStatus
    provider_name: str
    discovery_type: DiscoveryType | None = None
    event: EventCandidate | None = None
    place: PlaceCandidate | None = None
    evidence: DiscoveryEvidence | None = None
    reason: str | None = None
    discovery_unit_id: str | None = None

    @property
    def candidate(self) -> EventCandidate | PlaceCandidate | None:
        return self.event if self.event is not None else self.place


def build_candidate_id(raw_item: RawItem) -> str:
    """Identity of the candidate discovered in one exact RawItem observation.

    The same raw item id and content hash always yield the same id, an edited
    observation yields a new one, and the provider or model never affects it.
    """
    observation = f"{raw_item.id}\x1f{raw_item.content_hash}".encode("utf-8")
    return f"candidate:{hashlib.sha256(observation).hexdigest()}"


def build_extraction_input(raw_item: RawItem, source: Source | None = None) -> ExtractionInput:
    if source is not None and source.id != raw_item.source_id:
        raise ValueError(
            f"source {source.id} does not match raw item source {raw_item.source_id}"
        )
    return ExtractionInput(
        raw_item_id=raw_item.id,
        source_id=raw_item.source_id,
        source_type=raw_item.source_type.value,
        raw_text=raw_item.raw_text,
        content_url=raw_item.content_url,
        content_type=raw_item.content_type,
        published_at=raw_item.published_at,
        author=raw_item.author,
        locale=source.locale if source is not None else None,
        timezone=source.timezone if source is not None else None,
        city_hint=source.city_hint if source is not None else None,
    )


class DiscoveryService:
    """Deterministic application behavior around exactly one provider call per RawItem.

    It guards which observations are worth classifying, validates provider output, and
    maps it onto the candidate type the classification calls for, with provenance and
    identity taken from the RawItem itself. It holds no opinion about Persian or
    English event language — that vocabulary lives in `rules`, and the guard below
    only asks whether there are any content words at all.
    """

    def __init__(self, provider: DiscoveryProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def discover(self, raw_item: RawItem, source: Source | None = None) -> DiscoveryOutcome:
        units = primary_discovery_units(raw_item)
        if not units:
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_EMPTY_TEXT)
        caption_item = replace(raw_item, raw_text=units[0].text)
        return self._discover_raw(caption_item, source)

    def discover_units(
        self, raw_item: RawItem, units: tuple[DiscoveryUnit, ...],
        source: Source | None = None,
    ) -> tuple[DiscoveryOutcome, ...]:
        return tuple(self.discover_unit(raw_item, unit, source) for unit in units)

    def discover_unit(
        self, raw_item: RawItem, unit: DiscoveryUnit, source: Source | None = None
    ) -> DiscoveryOutcome:
        if unit.raw_item_id != raw_item.id:
            raise ValueError('discovery unit does not belong to the raw item')
        unit_hash = hashlib.sha256(
            (raw_item.content_hash + '\x1f' + unit.unit_id).encode('utf-8')
        ).hexdigest()
        unit_item = replace(raw_item, raw_text=unit.text, content_hash=unit_hash)
        outcome = self._discover_raw(unit_item, source)
        return replace(outcome, discovery_unit_id=unit.unit_id)

    def _discover_raw(
        self, raw_item: RawItem, source: Source | None = None
    ) -> DiscoveryOutcome:
        extraction_input = build_extraction_input(raw_item, source)
        if not raw_item.raw_text.strip():
            # No text is not evidence of anything, so this is not classified at all.
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_EMPTY_TEXT)
        if not has_meaningful_content(raw_item.raw_text):
            # Meaningless content is not an "other": nothing was actually analyzed.
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_INSUFFICIENT_TEXT)

        try:
            facts = validate_discovery_facts(self._provider.discover(extraction_input))
        except ProviderExtractionError as exc:
            return self._outcome(raw_item, DiscoveryStatus.PROVIDER_FAILED, reason=str(exc))
        except InvalidExtractionOutputError as exc:
            return self._outcome(raw_item, DiscoveryStatus.INVALID_OUTPUT, reason=str(exc))

        return self._outcome(
            raw_item,
            DiscoveryStatus.DISCOVERED,
            discovery_type=facts.discovery_type,
            event=_event_candidate(raw_item, facts),
            place=_place_candidate(raw_item, facts),
            evidence=facts.evidence,
        )

    def _outcome(
        self,
        raw_item: RawItem,
        status: DiscoveryStatus,
        *,
        discovery_type: DiscoveryType | None = None,
        event: EventCandidate | None = None,
        place: PlaceCandidate | None = None,
        evidence: DiscoveryEvidence | None = None,
        reason: str | None = None,
    ) -> DiscoveryOutcome:
        return DiscoveryOutcome(
            raw_item_id=raw_item.id,
            status=status,
            provider_name=self._provider.name,
            discovery_type=discovery_type,
            event=event,
            place=place,
            evidence=evidence,
            reason=reason,
        )


def _event_candidate(raw_item: RawItem, facts: DiscoveryFacts) -> EventCandidate | None:
    """An EventCandidate, or None when the observation was not an event.

    `starts_at`, `ends_at`, `price_amount`, and `currency` are owned by the later
    normalization step and stay null here; the source wording that would feed them
    stays in `source_date_text` and `price_text`.
    """
    if facts.discovery_type is not DiscoveryType.EVENT:
        return None
    return EventCandidate(
        candidate_id=build_candidate_id(raw_item),
        raw_item_id=raw_item.id,
        is_event=True,
        title=facts.title,
        summary=facts.summary,
        category=facts.category,
        source_date_text=facts.source_date_text,
        venue_name=facts.venue_name,
        address=facts.address,
        city=facts.city,
        event_format=facts.event_format,
        price_text=facts.price_text,
        registration_url=facts.registration_url,
        language=facts.language,
        extraction_confidence=facts.extraction_confidence,
        evidence_url=raw_item.content_url,
    )


def _place_candidate(raw_item: RawItem, facts: DiscoveryFacts) -> PlaceCandidate | None:
    if facts.discovery_type is not DiscoveryType.PLACE:
        return None
    return PlaceCandidate(
        candidate_id=build_candidate_id(raw_item),
        raw_item_id=raw_item.id,
        title=facts.title,
        summary=facts.summary,
        category=facts.category,
        address=facts.address,
        city=facts.city,
        opening_hours_text=facts.opening_hours_text,
        price_text=facts.price_text,
        language=facts.language,
        evidence_url=raw_item.content_url,
    )


__all__ = [
    "SKIP_EMPTY_TEXT",
    "SKIP_INSUFFICIENT_TEXT",
    "DiscoveryOutcome",
    "DiscoveryService",
    "DiscoveryStatus",
    "build_candidate_id",
    "build_extraction_input",
]
