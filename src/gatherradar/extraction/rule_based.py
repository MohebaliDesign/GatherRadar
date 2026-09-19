"""The deterministic, free discovery provider.

This is GatherRadar's default: no model, no API key, no network access, no cost. It
reads the signals found in the source text, scores them with the weights in `rules`,
and decides between an event, a place, and neither — then reports why.

Two ideas keep it honest.

**No single keyword decides anything.** An event needs a recognized path through the
evidence, not one word. Two paths are legitimate, because real captions come in two
shapes:

* **Path A** — event terminology together with date, time, or registration evidence.
  The classic announcement.
* **Path B** — strong event terminology or a validated named event, together with an
  invitation to attend, plus venue or location context when the terminology alone is
  not specific enough. This is the shape of a post that says where to come and when
  they are waiting for you without ever printing a date, and requiring a date was the
  tuning mistake that made the first version of this engine too strict.

An attendance invitation alone never creates an event, and neither does a date alone,
an address alone, or an event word alone.

**Evidence that it already happened counts against it, but never vetoes.** A recap
carries retrospective phrases; a post that is both a recap and an announcement of the
next occurrence can still outweigh them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import DiscoveryType
from . import fields, rules
from .models import DiscoveryEvidence, DiscoveryFacts, ExtractionInput
from .signals import SignalSet, analyze

PROVIDER_NAME = "rule-based/1"

REASON_EVENT_PATH_A = "event: terminology with date, time, or registration evidence"
REASON_EVENT_PATH_B = "event: event terminology with attendance and venue context"
REASON_PLACE = "place: place vocabulary with descriptive or visit context"
REASON_NO_EVENT_PATH = "other: no event or place path was satisfied"
REASON_BELOW_THRESHOLD = "other: evidence did not outweigh the score threshold"


@dataclass(frozen=True, slots=True)
class Scores:
    event: float = 0.0
    place: float = 0.0
    negative: float = 0.0

    @property
    def net_event(self) -> float:
        return self.event - self.negative

    @property
    def net_place(self) -> float:
        return self.place - self.negative


def score(found: SignalSet) -> Scores:
    """Add up the weighted evidence. Distinct terms count, repetitions do not."""
    event = 0.0
    strong = found.distinct_terms(found.event_strong)
    if strong:
        event += rules.WEIGHT_EVENT_TERM_STRONG + min(
            (strong - 1) * rules.WEIGHT_EVENT_TERM_STRONG_EXTRA, rules.MAX_EVENT_TERM_STRONG_EXTRA
        )
    weak = found.distinct_terms(found.event_weak)
    if weak:
        event += min(weak * rules.WEIGHT_EVENT_TERM_WEAK, rules.MAX_EVENT_TERM_WEAK)
    if found.named_event is not None:
        event += rules.WEIGHT_NAMED_EVENT
    if found.dates:
        event += rules.WEIGHT_DATE
    if found.times:
        event += rules.WEIGHT_TIME
    if found.registration:
        event += rules.WEIGHT_REGISTRATION
    if found.attendance:
        event += rules.WEIGHT_ATTENDANCE
    if found.prices:
        event += rules.WEIGHT_PRICE
    if found.locations:
        event += rules.WEIGHT_LOCATION

    place = 0.0
    place_terms = found.distinct_terms(found.place_terms)
    if place_terms:
        place += rules.WEIGHT_PLACE_TERM + min(
            (place_terms - 1) * rules.WEIGHT_PLACE_TERM_EXTRA, rules.MAX_PLACE_TERM_EXTRA
        )
    if found.place_context:
        place += rules.WEIGHT_PLACE_CONTEXT
    if found.locations:
        place += rules.WEIGHT_PLACE_LOCATION

    negative = found.distinct_terms(found.retrospective) * rules.WEIGHT_RETROSPECTIVE
    return Scores(event=event, place=place, negative=negative)


def classify(found: SignalSet) -> tuple[DiscoveryType, Scores, str]:
    """Decide what the observation is, and say why in one sentence."""
    scores = score(found)

    has_event_term = bool(found.event_strong or found.event_weak)
    has_strong_term = bool(found.event_strong)
    # A bare link is not occurrence evidence: Instagram captions carry links for
    # every reason. Registration has to be said in words to count.
    has_occurrence_evidence = bool(found.dates or found.times or found.registration)
    has_location_context = bool(found.locations or found.place_terms)

    path_a = has_event_term and has_occurrence_evidence
    path_b = bool(found.attendance) and (
        (has_strong_term and found.named_event is not None)
        or (has_strong_term and has_location_context)
    )

    if path_a or path_b:
        if scores.net_event >= rules.EVENT_SCORE_THRESHOLD:
            return DiscoveryType.EVENT, scores, REASON_EVENT_PATH_A if path_a else REASON_EVENT_PATH_B
        return DiscoveryType.OTHER, scores, REASON_BELOW_THRESHOLD

    place_path = bool(found.place_terms) and bool(found.place_context or found.locations)
    if place_path and scores.net_place >= rules.PLACE_SCORE_THRESHOLD:
        return DiscoveryType.PLACE, scores, REASON_PLACE

    return DiscoveryType.OTHER, scores, REASON_NO_EVENT_PATH


def _evidence(found: SignalSet, scores: Scores, reason: str) -> DiscoveryEvidence:
    return DiscoveryEvidence(
        event_score=round(scores.event, 2),
        place_score=round(scores.place, 2),
        negative_score=round(scores.negative, 2),
        matched_signals=found.labels_of(found.positive),
        negative_signals=found.labels_of(found.retrospective),
        reason=reason,
    )


def _event_facts(found: SignalSet, evidence: DiscoveryEvidence) -> DiscoveryFacts:
    return DiscoveryFacts(
        discovery_type=DiscoveryType.EVENT,
        title=fields.title(found, found.named_event),
        category=fields.category(found),
        source_date_text=fields.source_date_text(found),
        venue_name=fields.venue_name(found),
        address=fields.address(found),
        city=fields.city(found),
        event_format=fields.event_format(found),
        price_text=fields.price_text(found),
        registration_url=fields.registration_url(found),
        language=found.language,
        evidence=evidence,
    )


def _place_facts(found: SignalSet, evidence: DiscoveryEvidence) -> DiscoveryFacts:
    return DiscoveryFacts(
        discovery_type=DiscoveryType.PLACE,
        title=fields.title(found, found.named_place),
        summary=fields.place_summary(found),
        category=fields.place_category(found),
        address=fields.address(found),
        city=fields.city(found),
        price_text=fields.price_text(found),
        opening_hours_text=fields.opening_hours_text(found),
        language=found.language,
        evidence=evidence,
    )


class RuleBasedDiscoveryProvider:
    """A DiscoveryProvider that classifies and extracts with deterministic rules only.

    It is source-neutral: it reads `ExtractionInput`, so the same engine will serve
    website observations and any later public source family without change. It never
    reaches the outside world, so it cannot fail for operational reasons and never
    raises ProviderExtractionError.
    """

    name = PROVIDER_NAME

    def discover(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        found = analyze(extraction_input.raw_text)
        discovery_type, scores, reason = classify(found)
        evidence = _evidence(found, scores, reason)

        if discovery_type is DiscoveryType.EVENT:
            return _event_facts(found, evidence)
        if discovery_type is DiscoveryType.PLACE:
            return _place_facts(found, evidence)
        # "Other" means analyzed and found unrelated, so it carries no facts.
        return DiscoveryFacts(discovery_type=DiscoveryType.OTHER, evidence=evidence)


__all__ = [
    "PROVIDER_NAME",
    "REASON_BELOW_THRESHOLD",
    "REASON_EVENT_PATH_A",
    "REASON_EVENT_PATH_B",
    "REASON_NO_EVENT_PATH",
    "REASON_PLACE",
    "RuleBasedDiscoveryProvider",
    "Scores",
    "classify",
    "score",
]
