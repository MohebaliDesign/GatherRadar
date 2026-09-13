from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from ..domain import EventCandidate, RawItem, Source
from .base import EventExtractionProvider, InvalidExtractionOutputError, ProviderExtractionError
from .models import ExtractionInput
from .validation import validate_extracted_facts


class ExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    SKIPPED = "skipped"
    PROVIDER_FAILED = "provider_failed"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """Result of extracting one RawItem. Operational details stay here, not on EventCandidate."""

    raw_item_id: str
    status: ExtractionStatus
    provider_name: str
    candidate: EventCandidate | None = None
    reason: str | None = None


def build_candidate_id(raw_item: RawItem) -> str:
    """Identity of the candidate extracted from one exact RawItem observation.

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


class EventExtractionService:
    """Deterministic application behavior around exactly one provider call per RawItem:
    skips items without text, validates provider output, and maps it onto EventCandidate
    with provenance and identity taken from the RawItem itself."""

    def __init__(self, provider: EventExtractionProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def extract(self, raw_item: RawItem, source: Source | None = None) -> ExtractionOutcome:
        extraction_input = build_extraction_input(raw_item, source)
        if not raw_item.raw_text.strip():
            # No text is not evidence of a non-event, so this is not classified at all.
            return self._outcome(
                raw_item, ExtractionStatus.SKIPPED, reason="raw_text is empty; nothing to extract"
            )

        try:
            facts = validate_extracted_facts(self._provider.extract(extraction_input))
        except ProviderExtractionError as exc:
            return self._outcome(raw_item, ExtractionStatus.PROVIDER_FAILED, reason=str(exc))
        except InvalidExtractionOutputError as exc:
            return self._outcome(raw_item, ExtractionStatus.INVALID_OUTPUT, reason=str(exc))

        candidate = EventCandidate(
            candidate_id=build_candidate_id(raw_item),
            raw_item_id=raw_item.id,
            is_event=facts.is_event,
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
        return self._outcome(raw_item, ExtractionStatus.EXTRACTED, candidate=candidate)

    def _outcome(
        self,
        raw_item: RawItem,
        status: ExtractionStatus,
        *,
        candidate: EventCandidate | None = None,
        reason: str | None = None,
    ) -> ExtractionOutcome:
        return ExtractionOutcome(
            raw_item_id=raw_item.id,
            status=status,
            provider_name=self._provider.name,
            candidate=candidate,
            reason=reason,
        )
