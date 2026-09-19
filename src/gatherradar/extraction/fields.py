"""Source-supported field extraction for one classified observation.

Two rules govern everything here. Every value is a slice of the operator's own
text — never a rewrite, a summary, or a guess — and a field the source does not
support stays None. Nothing is normalized: Jalali dates, price amounts, and
timezones belong to the later normalization step, so `source_date_text` and
`price_text` keep the wording exactly as published.
"""

from __future__ import annotations

import re

from . import rules
from .signals import CITY_TOKENS, Signal, SignalSet
from .text import line_bounds, normalize

_MAX_PLACE_SUMMARY = 200
_TRIM = " \t‌؛،,;:-–—•*_"

# A leading day number that belongs with the month term it precedes: "۱۹ و ۲۰ شهریور".
_LEADING_NUMBERS = re.compile(r"(\d{1,4}(?:\s*(?:و|,|-|–|تا)\s*\d{1,4})*\s*)$")
# A trailing range that belongs with the time it follows: "از ساعت ۱۶ تا ۲۲".
_TRAILING_RANGE = re.compile(r"^(\s*(?:تا|to|-|–|—)\s*\d{1,2}(?::\d{2})?)")


def _line(text: str, position: int) -> str:
    start, end = line_bounds(text, position)
    return text[start:end].strip(_TRIM)


def _labelled_value(found: SignalSet, name: str) -> str | None:
    """The operator's value for a labelled field, e.g. the text after "آدرس:".

    When the label ends its line, the value is taken from the next non-empty line,
    which is how addresses are often written.
    """
    position = found.labels.get(name)
    if position is None:
        return None
    _, value_start = position
    _, line_end = line_bounds(found.text, value_start)
    value = found.text[value_start:line_end].strip(_TRIM)
    if value:
        return value
    for line in found.text[line_end:].splitlines():
        stripped = line.strip(_TRIM)
        if stripped:
            return stripped
    return None


def _first(signals: tuple[Signal, ...]) -> Signal | None:
    return signals[0] if signals else None


def title(found: SignalSet, named: Signal | None) -> str | None:
    """A title only from a validated named construction or an explicit quoted name.

    Deliberately not "the first line that mentions an event word": a line like
    "اینجا فقط ایونت نیست" mentions one and names nothing, so it yields None.
    """
    return named.text.strip(_TRIM) or None if named is not None else None


def source_date_text(found: SignalSet) -> str | None:
    """The source's own date and time wording, unconverted.

    A labelled value wins. Otherwise the line carrying the most temporal signals is
    used, narrowed to the span those signals cover and widened over a leading day
    number ("۱۹ و ۲۰ شهریور") or a trailing range ("از ساعت ۱۶ تا ۲۲").
    """
    labelled = _labelled_value(found, "date")
    if labelled:
        return labelled

    temporal = found.dates + found.times
    if not temporal:
        return None

    lines: dict[tuple[int, int], list[Signal]] = {}
    for signal in temporal:
        lines.setdefault(line_bounds(found.text, signal.start), []).append(signal)
    bounds, signals = max(lines.items(), key=lambda item: (len(item[1]), -item[0][0]))

    line_start, line_end = bounds
    start = min(signal.start for signal in signals)
    end = max(signal.end for signal in signals)

    leading = _LEADING_NUMBERS.search(found.normalized[line_start:start])
    if leading:
        start = line_start + leading.start(1)
    trailing = _TRAILING_RANGE.match(found.normalized[end:line_end])
    if trailing:
        end += trailing.end(1)

    return found.text[start:end].strip(_TRIM) or None


def venue_name(found: SignalSet) -> str | None:
    """Only an explicitly labelled venue; a place word in a sentence is not one."""
    return _labelled_value(found, "venue")


def address(found: SignalSet) -> str | None:
    return _labelled_value(found, "address")


def city(found: SignalSet) -> str | None:
    """A city only when the text says one, in the source's own wording.

    A neighborhood never implies its city: "نیاوران" yields None, while an explicit
    "تهران" yields "تهران".
    """
    labelled = _labelled_value(found, "city")
    if labelled:
        return labelled
    for token in found.tokens:
        if token.text in CITY_TOKENS:
            return found.text[token.start : token.end]
    return None


def event_format(found: SignalSet) -> str | None:
    """`online`, `in_person`, `hybrid`, or None — explicit wording only.

    An address is never taken as proof that an event is in person.
    """
    normalized = found.normalized
    has_online = any(normalize(term) in normalized for term in rules.ONLINE_TERMS)
    has_in_person = any(normalize(term) in normalized for term in rules.IN_PERSON_TERMS)
    if any(normalize(term) in normalized for term in rules.HYBRID_TERMS) or (has_online and has_in_person):
        return "hybrid"
    if has_online:
        return "online"
    if has_in_person:
        return "in_person"
    return None


def price_text(found: SignalSet) -> str | None:
    """The source's own price wording, including "رایگان"; never a parsed amount."""
    labelled = _labelled_value(found, "price")
    if labelled:
        return labelled
    signal = _first(found.prices)
    return _line(found.text, signal.start) or None if signal is not None else None


def registration_url(found: SignalSet) -> str | None:
    signal = _first(found.urls)
    return signal.text if signal is not None else None


def opening_hours_text(found: SignalSet) -> str | None:
    """The line a place uses to state when it is open, unconverted."""
    for signal in found.place_context:
        if signal.term in rules.OPENING_HOURS_TERMS:
            line = _line(found.text, signal.start)
            if line:
                return line
    return None


def category(found: SignalSet) -> str | None:
    """A controlled category, only from a term whose category wording is unambiguous."""
    for signal in found.event_strong + found.event_weak:
        mapped = rules.EVENT_CATEGORIES.get(signal.term)
        if mapped:
            return mapped
    return None


def place_category(found: SignalSet) -> str | None:
    for signal in found.place_terms:
        mapped = rules.PLACE_CATEGORIES.get(signal.term)
        if mapped:
            return mapped
    return None


def place_summary(found: SignalSet) -> str | None:
    """The source's own one-line description of itself, quoted rather than written."""
    signal = _first(found.place_terms)
    if signal is None:
        return None
    line = _line(found.text, signal.start)
    return line if line and len(line) <= _MAX_PLACE_SUMMARY else None


__all__ = [
    "address",
    "category",
    "city",
    "event_format",
    "opening_hours_text",
    "place_category",
    "place_summary",
    "price_text",
    "registration_url",
    "source_date_text",
    "title",
    "venue_name",
]
