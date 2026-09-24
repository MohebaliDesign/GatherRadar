from __future__ import annotations

from dataclasses import replace
import re

from ..domain import EventCandidate, PlaceCandidate, RawItem, Source
from .models import Diagnostic, NormalizationOutcome, Severity, TemporalResult
from .prices import normalize_price
from .temporal import normalize_temporal
from .text import fold


class NormalizationService:
    """Pure interpretation of discovered fields. Identity and wording never change."""

    def normalize(
        self, candidate: EventCandidate | PlaceCandidate, raw_item: RawItem, source: Source,
        *, evidence_text: str | None = None,
    ) -> NormalizationOutcome:
        if candidate.raw_item_id != raw_item.id or source.id != raw_item.source_id or source.source_type != raw_item.source_type:
            return NormalizationOutcome(candidate, diagnostics=(Diagnostic(
                "context_mismatch", "provenance", "Candidate, observation and source must correspond.", Severity.ERROR,
            ),))
        price = normalize_price(candidate.price_text)
        if isinstance(candidate, PlaceCandidate):
            return NormalizationOutcome(candidate, price=price, diagnostics=price.diagnostics)
        temporal = normalize_temporal(candidate.source_date_text, raw_item, source)
        # Discovery may select a relative token from ordinary prose or a proper name.
        # A bare token needs a standalone temporal line in the exact discovery unit.
        wording = fold(candidate.source_date_text or "")
        if wording in {"امروز", "فردا", "today", "tomorrow"} and temporal.start_date is not None:
            evidence = raw_item.raw_text if evidence_text is None else evidence_text
            lines = (re.sub(r"^(?:زمان|تاریخ|date|when)\s*[:：]\s*", "", fold(line)).strip(" .،؛📅🗓")
                     for line in evidence.splitlines())
            if wording not in lines:
                temporal = TemporalResult(
                    timezone=temporal.timezone, reference_at=temporal.reference_at,
                    reference_basis=temporal.reference_basis,
                    diagnostics=(Diagnostic("ambiguous_relative_context", "source_date_text",
                                            "Bare relative word is not a standalone or labelled temporal line in the evidence."),),
                )
        updated = replace(candidate, **{
            name: getattr(temporal, name) for name in (
                "start_date", "end_date", "start_time", "end_time", "starts_at", "ends_at", "timezone", "date_precision",
            )
        }, price_amount=price.price_amount, currency=price.currency)
        return NormalizationOutcome(updated, temporal, price, temporal.diagnostics + price.diagnostics)
