"""Source-supported field extraction for one classified observation.

Two rules govern everything here. Every value is a slice of the operator's own
text — never a rewrite, a summary, or a guess — and a field the source does not
support stays None. Nothing is normalized: Jalali dates, price amounts, and
timezones belong to the later normalization step, so `source_date_text` and
`price_text` keep the wording exactly as published.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import rules
from .signals import CITY_TOKENS, Signal, SignalSet
from .text import line_bounds, normalize, tokenize

_MAX_PLACE_SUMMARY = 200
_TRIM = " \t\r‌؛،,;:-–—•*_\u2066\u2067\u2068\u2069\ufeff"

# A leading day number that belongs with the month term it precedes: "۱۹ و ۲۰ شهریور".
_LEADING_NUMBERS = re.compile(r"(\d{1,4}(?:\s*(?:و|,|-|–|تا)\s*\d{1,4})*\s*)$")
# A trailing range that belongs with the time it follows: "از ساعت ۱۶ تا ۲۲".
_TRAILING_RANGE = re.compile(r"^(\s*(?:تا|to|-|–|—)\s*\d{1,2}(?::\d{2})?)")
_EXPLICIT_FREE = re.compile(r"(?<!\w)(?:رایگان|بدون\s+هزینه|free|no\s+fee)(?!\w)")
_AMOUNT_WITH_CURRENCY = re.compile(
    r"(?:[$€£]\s*\d[\d\s,٬،.]*)|"
    r"(?:\d[\d\s,٬،.]*(?:هزار|میلیون|million|thousand)?\s*"
    r"(?:تومان|تومن|ریال|دلار|usd|eur|gbp|dollars?))\b"
)
_ANY_AMOUNT = re.compile(r"(?<!\w)\d[\d\s,٬،.]*(?!\w)")
_TEMPORAL_CONNECTORS = frozenset({"و", "تا", "الی", "از", "ماه", "and", "to", "at"})


@dataclass(frozen=True, slots=True)
class _TemporalFragment:
    start: int
    end: int
    line_start: int
    line_end: int
    signals: tuple[Signal, ...]

    @property
    def has_date(self) -> bool:
        return any(signal.kind == "date" for signal in self.signals)

    @property
    def has_time(self) -> bool:
        return any(signal.kind == "time" for signal in self.signals)

    @property
    def has_concrete_date(self) -> bool:
        return any(
            signal.kind == "date" and signal.term not in rules.RELATIVE_DATES
            for signal in self.signals
        )

    @property
    def visual(self) -> bool:
        return any(signal.term.startswith("visual_") for signal in self.signals)


def _line(text: str, position: int) -> str:
    start, end = line_bounds(text, position)
    return text[start:end].strip(_TRIM)


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start] in _TRIM:
        start += 1
    while end > start and text[end - 1] in _TRIM:
        end -= 1
    return (start, end) if start < end else None


def _labelled_span(found: SignalSet, name: str) -> tuple[int, int] | None:
    """The operator's value for a labelled field, e.g. the text after "آدرس:".

    When the label ends its line, the value is taken from the next non-empty line,
    which is how addresses are often written.
    """
    position = found.labels.get(name)
    if position is None:
        return None
    _, value_start = position
    _, line_end = line_bounds(found.text, value_start)
    span = _trimmed_span(found.text, value_start, line_end)
    if span is not None:
        return span

    cursor = line_end
    while cursor < len(found.text):
        cursor += 1 if found.text[cursor : cursor + 1] == "\n" else 0
        _, next_end = line_bounds(found.text, cursor)
        span = _trimmed_span(found.text, cursor, next_end)
        if span is not None:
            return span
        if next_end == len(found.text):
            break
        cursor = next_end
    return None


def _labelled_value(found: SignalSet, name: str) -> str | None:
    span = _labelled_span(found, name)
    return found.text[slice(*span)] if span is not None else None


def _first(signals: tuple[Signal, ...]) -> Signal | None:
    return signals[0] if signals else None


def title(found: SignalSet, named: Signal | None) -> str | None:
    """A title only from a validated named construction or an explicit quoted name.

    Deliberately not "the first line that mentions an event word": a line like
    "اینجا فقط ایونت نیست" mentions one and names nothing, so it yields None.
    """
    return named.text.strip(_TRIM) or None if named is not None else None


def _temporal_gap_is_related(gap: str) -> bool:
    if len(gap) > 40 or any(char in gap for char in "؟?!؛;"):
        return False
    tokens = tuple(token.text for token in tokenize(normalize(gap)))
    return all(token.isdigit() or token in _TEMPORAL_CONNECTORS for token in tokens)


def _temporal_fragments(found: SignalSet) -> list[_TemporalFragment]:
    by_line: dict[tuple[int, int], list[Signal]] = {}
    for signal in found.dates + found.times:
        by_line.setdefault(line_bounds(found.text, signal.start), []).append(signal)

    fragments: list[_TemporalFragment] = []
    for (line_start, line_end), line_signals in by_line.items():
        clusters: list[list[Signal]] = []
        for signal in sorted(line_signals, key=lambda item: (item.start, -item.end)):
            if not clusters:
                clusters.append([signal])
                continue
            cluster_end = max(item.end for item in clusters[-1])
            if signal.start <= cluster_end or _temporal_gap_is_related(
                found.normalized[cluster_end:signal.start]
            ):
                clusters[-1].append(signal)
            else:
                clusters.append([signal])

        for cluster in clusters:
            start = min(signal.start for signal in cluster)
            end = max(signal.end for signal in cluster)
            leading = _LEADING_NUMBERS.search(found.normalized[line_start:start])
            if leading:
                start = line_start + leading.start(1)
            trailing = _TRAILING_RANGE.match(found.normalized[end:line_end])
            if trailing:
                end += trailing.end(1)
            trimmed = _trimmed_span(found.text, start, end)
            if trimmed is not None:
                fragments.append(
                    _TemporalFragment(
                        start=trimmed[0],
                        end=trimmed[1],
                        line_start=line_start,
                        line_end=line_end,
                        signals=tuple(cluster),
                    )
                )
    return fragments


def _fragment_rank(fragment: _TemporalFragment) -> tuple[int, int, int, int, int]:
    return (
        int(fragment.visual),
        int(fragment.has_date and fragment.has_time),
        int(fragment.has_concrete_date),
        int(fragment.has_time),
        -fragment.start,
    )


def _adjacent(first: _TemporalFragment, second: _TemporalFragment, text: str) -> bool:
    earlier, later = sorted((first, second), key=lambda item: item.line_start)
    return text[earlier.line_end : later.line_start] in {"\n", "\r\n"}


def _with_adjacent_complement(
    found: SignalSet,
    selected: _TemporalFragment,
    fragments: list[_TemporalFragment],
) -> str:
    selected_terms = {signal.term for signal in selected.signals}
    visual_counterpart = None
    if "visual_calendar" in selected_terms:
        visual_counterpart = "visual_clock"
    elif "visual_clock" in selected_terms:
        visual_counterpart = "visual_calendar"
    if visual_counterpart is not None:
        visual_neighbours = [
            fragment
            for fragment in fragments
            if fragment is not selected
            and _adjacent(selected, fragment, found.text)
            and any(signal.term == visual_counterpart for signal in fragment.signals)
        ]
        if visual_neighbours:
            complement = max(visual_neighbours, key=_fragment_rank)
            first, second = sorted((selected, complement), key=lambda item: item.start)
            return f"{found.text[first.start:first.end]}\n{found.text[second.start:second.end]}"

    if selected.has_date and selected.has_time:
        return found.text[selected.start:selected.end]

    complements = [
        fragment
        for fragment in fragments
        if fragment is not selected
        and _adjacent(selected, fragment, found.text)
        and (
            (selected.has_date and fragment.has_time)
            or (selected.has_time and fragment.has_date)
        )
    ]
    if not complements:
        return found.text[selected.start:selected.end]

    complement = max(complements, key=_fragment_rank)
    first, second = sorted((selected, complement), key=lambda item: item.start)
    return f"{found.text[first.start:first.end]}\n{found.text[second.start:second.end]}"


def source_date_text(found: SignalSet) -> str | None:
    """The source's own date and time wording, unconverted.

    A labelled value wins. Otherwise compact temporal fragments are preferred over
    conversational prose. Complementary date and time fragments on adjacent lines
    are kept together without joining unrelated paragraphs.
    """
    fragments = _temporal_fragments(found)
    labelled_span = _labelled_span(found, "date")
    if labelled_span is not None:
        start, end = labelled_span
        overlapping = tuple(
            signal
            for signal in found.dates + found.times
            if start <= signal.start < end or signal.start <= start < signal.end
        )
        labelled = _TemporalFragment(
            start=start,
            end=end,
            line_start=line_bounds(found.text, start)[0],
            line_end=line_bounds(found.text, start)[1],
            signals=overlapping or (Signal("date", "labelled_date", found.text[start:end], start, end),),
        )
        return _with_adjacent_complement(found, labelled, fragments)

    if not fragments:
        return None
    selected = max(fragments, key=_fragment_rank)
    return _with_adjacent_complement(found, selected, fragments).strip(_TRIM) or None


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
    address_span = _labelled_span(found, "address")
    if address_span is not None:
        address_start, address_end = address_span
        for token in found.tokens:
            if address_start <= token.start < address_end and token.text in CITY_TOKENS:
                return found.text[token.start : token.end]
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
    """Conservative source price wording; a bare price-related word is not enough."""
    labelled = _labelled_value(found, "price")
    if labelled:
        normalized = normalize(labelled)
        if (
            _EXPLICIT_FREE.search(normalized)
            or _AMOUNT_WITH_CURRENCY.search(normalized)
            or _ANY_AMOUNT.search(normalized)
        ):
            return labelled

    seen_lines: set[tuple[int, int]] = set()
    for signal in found.prices:
        bounds = line_bounds(found.text, signal.start)
        if bounds in seen_lines:
            continue
        seen_lines.add(bounds)
        line = found.text[slice(*bounds)].strip(_TRIM)
        normalized = normalize(line)
        if _EXPLICIT_FREE.search(normalized) or _AMOUNT_WITH_CURRENCY.search(normalized):
            return line
    return None


def registration_url(found: SignalSet) -> str | None:
    """A URL explicitly associated with registration wording on its source line."""
    candidates: list[tuple[int, int, str]] = []
    for url in found.urls:
        url_line = line_bounds(found.text, url.start)
        for context in found.registration:
            if line_bounds(found.text, context.start) != url_line:
                continue
            distance = max(context.start - url.end, url.start - context.end, 0)
            candidates.append((distance, url.start, url.text))
    return min(candidates)[2] if candidates else None


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
