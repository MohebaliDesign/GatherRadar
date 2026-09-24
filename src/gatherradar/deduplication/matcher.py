"""Explainable pair decisions. No scores, source-specific trust, or transitivity."""
from __future__ import annotations

from ..domain import EventCandidate
from ..domain.temporal import DatePrecision
from .keys import registration_key, text_key, title_relation
from .models import CandidateContext, DuplicateDecision, MatchKind


def temporal_reliable(context: CandidateContext) -> bool:
    # Even RANGE with inferred_year must never masquerade as an explicit date.
    c = context.candidate
    diagnostics = context.outcome.diagnostics + (context.outcome.temporal.diagnostics
                                                if context.outcome.temporal is not None else ())
    return (isinstance(c, EventCandidate) and c.start_date is not None
            and c.date_precision in {DatePrecision.EXACT, DatePrecision.DAY}
            and c.end_date is None
            and not any(d.field not in {"price_text", "price_amount", "currency"}
                        for d in diagnostics))


def match_pair(left: CandidateContext, right: CandidateContext) -> DuplicateDecision:
    ids = tuple(sorted((left.candidate_id, right.candidate_id)))
    a, b = left.candidate, right.candidate
    if not isinstance(a, EventCandidate) or not isinstance(b, EventCandidate):
        return DuplicateDecision(ids, MatchKind.INSUFFICIENT, ("not_two_events",))
    reasons: list[str] = []
    conflicts: list[str] = []
    reliable = temporal_reliable(left) and temporal_reliable(right)
    same_date = a.start_date is not None and a.start_date == b.start_date
    if a.start_date and b.start_date:
        if same_date:
            reasons.append("exact_date_match" if reliable else "uncertain_date_match")
        elif reliable:
            conflicts.append("conflicting_exact_date")
        else:
            reasons.append("uncertain_date_difference")
    title = title_relation(a.title, b.title)
    if title in {"exact", "strong"}:
        reasons.append("distinctive_title_" + title)
    elif title == "different":
        conflicts.append("distinctive_title_conflict")
    elif title == "partial":
        reasons.append("title_similarity_only")

    matched_location = False
    for field in ("city", "venue_name", "address"):
        x, y = getattr(a, field), getattr(b, field)
        if x and y:
            if text_key(x) == text_key(y):
                reasons.append(field + "_match")
                if field != "city":
                    matched_location = True
            else:
                conflicts.append(field + "_conflict")
    zone_match = bool(a.timezone and a.timezone == b.timezone)
    if a.timezone and b.timezone and not zone_match:
        conflicts.append("timezone_conflict")
    same_time = bool(zone_match and a.start_time is not None and a.start_time == b.start_time)
    for field in ("start_time", "end_time"):
        x, y = getattr(a, field), getattr(b, field)
        if x is not None and y is not None:
            if x == y and zone_match:
                reasons.append(field + "_match")
            elif x != y and reliable and zone_match:
                conflicts.append("conflicting_" + field)
            elif x != y:
                reasons.append("uncertain_" + field + "_difference")
    homes = (left.source.url, right.source.url)
    u, v = registration_key(a.registration_url, homes), registration_key(b.registration_url, homes)
    same_registration = bool(u and u == v)
    if same_registration:
        reasons.append("registration_url_match")
    elif u and v:
        # Multiple vendors may sell the same occurrence; never infer identity
        # semantics from arbitrary URL path/query differences.
        reasons.append("different_registration_urls")
    publisher = left.source.publisher_key == right.source.publisher_key
    if publisher:
        reasons.append("same_publisher")
    if conflicts:
        return DuplicateDecision(ids, MatchKind.DISTINCT, tuple(sorted(conflicts + reasons)))
    strong_title = title in {"exact", "strong"}
    if (strong_title and same_date and reliable and zone_match
            and (publisher or (same_time and (matched_location or same_registration)))):
        return DuplicateDecision(ids, MatchKind.SAME_EVENT, tuple(sorted(reasons)))
    possible = (strong_title or same_registration
                or (same_date and (matched_location or "city_match" in reasons)))
    reasons.append("insufficient_occurrence_evidence")
    return DuplicateDecision(ids, MatchKind.POSSIBLE_DUPLICATE if possible else MatchKind.INSUFFICIENT,
                             tuple(sorted(reasons)))
