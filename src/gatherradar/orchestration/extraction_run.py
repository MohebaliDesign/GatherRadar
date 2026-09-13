from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..domain import EventCandidate, RawItem, Source
from ..extraction import EventExtractionService, ExtractionOutcome, ExtractionStatus


@dataclass(frozen=True, slots=True)
class ExtractionRunSummary:
    provider_name: str
    outcomes: tuple[ExtractionOutcome, ...] = ()

    @property
    def observed(self) -> int:
        return len(self.outcomes)

    @property
    def extracted(self) -> int:
        return self._count(ExtractionStatus.EXTRACTED)

    @property
    def events(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.is_event)

    @property
    def non_events(self) -> int:
        return sum(1 for candidate in self.candidates if not candidate.is_event)

    @property
    def skipped(self) -> int:
        return self._count(ExtractionStatus.SKIPPED)

    @property
    def failed(self) -> int:
        return self._count(ExtractionStatus.PROVIDER_FAILED) + self._count(ExtractionStatus.INVALID_OUTPUT)

    @property
    def candidates(self) -> tuple[EventCandidate, ...]:
        return tuple(outcome.candidate for outcome in self.outcomes if outcome.candidate is not None)

    def _count(self, status: ExtractionStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)


def run_event_extraction(
    raw_items: Iterable[RawItem],
    service: EventExtractionService,
    *,
    sources: Mapping[str, Source] | None = None,
) -> ExtractionRunSummary:
    """Extract every RawItem independently; a failed item never discards the others.

    `sources` maps source ids to their configuration, used as optional extraction context.
    Candidates are returned in memory only: EventCandidate is a transient boundary and is
    not persisted.
    """
    known_sources = sources or {}
    outcomes = tuple(
        service.extract(raw_item, known_sources.get(raw_item.source_id)) for raw_item in raw_items
    )
    return ExtractionRunSummary(provider_name=service.provider_name, outcomes=outcomes)


__all__ = ["ExtractionRunSummary", "run_event_extraction"]
