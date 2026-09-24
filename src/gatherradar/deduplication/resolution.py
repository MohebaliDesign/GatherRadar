"""Source-supported field selection with explicit unresolved conflicts."""
from __future__ import annotations

from ..domain import Event
from ..domain.event import CanonicalDiagnostic, FieldProvenance
from ..domain.temporal import DatePrecision
from .keys import stable_id, text_key
from .matcher import temporal_reliable
from .models import CandidateContext

TEMPORAL_FIELDS = ("start_date", "end_date", "start_time", "end_time", "timezone",
                   "starts_at", "ends_at", "date_precision")
TEXT_FIELDS = ("title", "summary", "category", "source_date_text", "venue_name", "address",
               "city", "event_format", "price_text", "registration_url", "language")
FOLDED_FIELDS = frozenset({"title", "venue_name", "address", "city", "category", "language"})


def anchor_order(context: CandidateContext) -> tuple:
    return (context.first_seen_at, context.raw_item.id, context.identity_slot, context.candidate_id)


def resolve_group(members: tuple[CandidateContext, ...], group_id: str) -> Event:
    ordered = sorted(members, key=anchor_order)
    anchor = ordered[0]
    ids = tuple(sorted(c.candidate_id for c in members))
    diagnostics: list[CanonicalDiagnostic] = []
    provenance: list[FieldProvenance] = []
    values: dict = {}

    def resolve(field: str, pool: list[CandidateContext]):
        populated = [(c, getattr(c.candidate, field)) for c in pool
                     if getattr(c.candidate, field) is not None]
        if not populated:
            return None
        def key(value):
            return text_key(value) if field in FOLDED_FIELDS else value
        distinct = {key(value) for _, value in populated}
        if len(distinct) > 1:
            diagnostics.append(CanonicalDiagnostic("field_conflict", field,
                               tuple(sorted(c.candidate_id for c, _ in populated))))
            return None
        value = populated[0][1]
        provenance.append(FieldProvenance(field, tuple(sorted(
            c.candidate_id for c, v in populated if key(v) == key(value)))))
        return value

    for field in TEXT_FIELDS:
        values[field] = resolve(field, ordered)
    values["extraction_confidence"] = resolve("extraction_confidence", ordered)

    # Monetary amount and stated unit are inseparable: never combine a free
    # amount from one source with a paid currency from another.
    prices = [(c, (c.candidate.price_amount, c.candidate.currency)) for c in ordered
              if c.candidate.price_amount is not None or c.candidate.currency is not None]
    if prices:
        if len({value for _, value in prices}) == 1:
            values["price_amount"], values["currency"] = prices[0][1]
            for field in ("price_amount", "currency"):
                if values[field] is not None:
                    provenance.append(FieldProvenance(field, tuple(sorted(c.candidate_id for c, _ in prices))))
        else:
            diagnostics.append(CanonicalDiagnostic("field_conflict", "price", tuple(sorted(c.candidate_id for c, _ in prices))))

    # Resolve temporal interpretations atomically. This preserves every chosen
    # tuple as supplied by Stage 7, including partial/range/inferred semantics.
    # Unknown components do not conflict; use an existing tuple that covers the
    # other tuples, never synthesize a new datetime/date-range from fragments.
    temporal = [c for c in ordered if any(getattr(c.candidate, f) is not None
                for f in TEMPORAL_FIELDS if f not in {"date_precision", "timezone"})]
    chosen = None
    if temporal:
        strongest = [c for c in temporal if temporal_reliable(c)] or temporal
        def compatible(a, b):
            return all(getattr(a.candidate, f) is None or getattr(b.candidate, f) is None
                       or getattr(a.candidate, f) == getattr(b.candidate, f)
                       for f in TEMPORAL_FIELDS if f != "date_precision")
        if all(compatible(a, b) for a in strongest for b in strongest):
            covering = [a for a in strongest if all(
                getattr(b.candidate, f) is None or getattr(a.candidate, f) == getattr(b.candidate, f)
                for b in strongest for f in TEMPORAL_FIELDS if f != "date_precision")]
            if covering:
                chosen = covering[0]
        if chosen is None:
            diagnostics.append(CanonicalDiagnostic("unresolved_temporal_interpretations", "temporal", ids))
        elif any(not compatible(chosen, c) for c in temporal):
            diagnostics.append(CanonicalDiagnostic("stronger_explicit_temporal_selected", "temporal", ids))
    if chosen is not None:
        for field in TEMPORAL_FIELDS:
            value = getattr(chosen.candidate, field)
            values[field] = value
            if value is not None:
                provenance.append(FieldProvenance(field, tuple(sorted(c.candidate_id for c in ordered
                    if getattr(c.candidate, field) == value))))
        # Complementary weaker values are still visible through membership and
        # this diagnostic; no information is silently interpreted as absent.
        if any(getattr(c.candidate, f) is not None and values[f] is None
               for c in temporal for f in TEMPORAL_FIELDS):
            diagnostics.append(CanonicalDiagnostic("partial_temporal_not_combined", "temporal", ids))
    else:
        values["date_precision"] = DatePrecision.UNKNOWN
        values["timezone"] = resolve("timezone", ordered)

    for context in ordered:
        for diagnostic in context.outcome.diagnostics:
            diagnostics.append(CanonicalDiagnostic("normalization:" + diagnostic.code, diagnostic.field,
                                                   (context.candidate_id,)))
    if values["title"] is None:
        diagnostics.append(CanonicalDiagnostic("missing_canonical_title", "title", ids))
    url = anchor.candidate.evidence_url or anchor.raw_item.content_url
    provenance.append(FieldProvenance("canonical_source_url", (anchor.candidate_id,)))
    return Event(
        event_id=stable_id("event:", (anchor.raw_item.id, anchor.identity_slot)),
        canonical_source_url=url,
        first_seen_at=min(c.first_seen_at for c in members),
        last_seen_at=max(c.raw_item.captured_at for c in members),
        identity_anchor_raw_item_id=anchor.raw_item.id, identity_anchor_slot=anchor.identity_slot,
        candidate_ids=ids,
        source_item_ids=tuple(sorted({c.raw_item.id for c in members})),
        source_ids=tuple(sorted({c.source.id for c in members})),
        publisher_keys=tuple(sorted({c.source.publisher_key for c in members})),
        evidence_urls=tuple(sorted({u for c in members for u in
                                  (c.candidate.evidence_url, c.raw_item.content_url) if u})),
        duplicate_group_id=group_id,
        field_provenance=tuple(sorted(provenance, key=lambda p: p.field)),
        diagnostics=tuple(sorted(set(diagnostics), key=lambda d: (d.code, d.field, d.candidate_ids))),
        **values,
    )
