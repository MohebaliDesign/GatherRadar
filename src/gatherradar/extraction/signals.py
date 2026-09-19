"""Explainable signal detection over one source text.

Every finding is a `Signal` that names what was recognized, which vocabulary entry
recognized it, and where it sits in the original text. Nothing here decides what the
content *is* — `rule_based` does that from these signals — and nothing here rewrites
or normalizes source wording.

Detection order matters in one place: retrospective phrases claim their words first,
so "هفته گذشته" in a recap is read as evidence the occurrence is over rather than as
a date for a future one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from . import rules
from .text import (
    PhraseMatch,
    Token,
    compile_vocabulary,
    detect_language,
    find_phrases,
    has_meaningful_content as _has_meaningful_content,
    line_bounds,
    normalize,
    phrase_tokens,
    tokenize,
)

URL_PATTERN = re.compile(r"https?://[^\s<>«»“”\"']+")
_URL_TRAILING = ".,;:!?)]}،؛؟»”\"'"

_TIME_RES = tuple(re.compile(pattern) for pattern in rules.TIME_PATTERNS)
_DATE_RES = tuple(re.compile(pattern) for pattern in rules.DATE_PATTERNS)


@dataclass(frozen=True, slots=True)
class Signal:
    """One recognized piece of evidence, traceable back to the source text."""

    kind: str
    term: str
    text: str
    start: int
    end: int
    first_token: int = -1
    last_token: int = -1

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.term}"


@dataclass(frozen=True, slots=True)
class SignalSet:
    """Everything the engine noticed in one observation."""

    text: str
    normalized: str
    tokens: tuple[Token, ...]
    language: str | None = None
    event_strong: tuple[Signal, ...] = ()
    event_weak: tuple[Signal, ...] = ()
    dates: tuple[Signal, ...] = ()
    times: tuple[Signal, ...] = ()
    place_terms: tuple[Signal, ...] = ()
    place_context: tuple[Signal, ...] = ()
    attendance: tuple[Signal, ...] = ()
    retrospective: tuple[Signal, ...] = ()
    registration: tuple[Signal, ...] = ()
    prices: tuple[Signal, ...] = ()
    locations: tuple[Signal, ...] = ()
    urls: tuple[Signal, ...] = ()
    named_event: Signal | None = None
    named_place: Signal | None = None
    labels: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def positive(self) -> tuple[Signal, ...]:
        return (
            self.event_strong
            + self.event_weak
            + ((self.named_event,) if self.named_event else ())
            + self.dates
            + self.times
            + self.registration
            + self.attendance
            + self.prices
            + self.locations
            + self.place_terms
            + self.place_context
        )

    def labels_of(self, signals: Sequence[Signal]) -> tuple[str, ...]:
        """Stable, de-duplicated signal labels in text order, for run evidence."""
        seen: dict[str, None] = {}
        for signal in sorted(signals, key=lambda item: (item.start, item.kind)):
            seen.setdefault(signal.label, None)
        return tuple(seen)

    def distinct_terms(self, signals: Sequence[Signal]) -> int:
        return len({signal.term for signal in signals})


@lru_cache(maxsize=None)
def _vocabulary(phrases: tuple[str, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return compile_vocabulary(phrases)


def _signals(
    kind: str,
    text: str,
    tokens: Sequence[Token],
    phrases: tuple[str, ...],
    *,
    blocked: frozenset[int] = frozenset(),
) -> tuple[Signal, ...]:
    return tuple(
        _from_match(kind, text, match) for match in find_phrases(tokens, _vocabulary(phrases), blocked=blocked)
    )


def _from_match(kind: str, text: str, match: PhraseMatch) -> Signal:
    return Signal(
        kind=kind,
        term=match.phrase,
        text=text[match.start : match.end],
        start=match.start,
        end=match.end,
        first_token=match.first_token,
        last_token=match.last_token,
    )


def _token_span(signals: Sequence[Signal]) -> frozenset[int]:
    claimed: set[int] = set()
    for signal in signals:
        if signal.first_token >= 0:
            claimed.update(range(signal.first_token, signal.last_token + 1))
    return frozenset(claimed)


def _neighbours_have_a_number(tokens: Sequence[Token], match: PhraseMatch) -> bool:
    for index in (match.first_token - 1, match.last_token + 1):
        if 0 <= index < len(tokens) and tokens[index].text.isdigit():
            return True
    return False


def _date_signals(
    text: str, normalized: str, tokens: Sequence[Token], blocked: frozenset[int]
) -> tuple[Signal, ...]:
    found: list[Signal] = []
    for match in find_phrases(tokens, _vocabulary(rules.DATE_TERMS), blocked=blocked):
        if match.phrase in rules.MONTHS_NEEDING_A_NUMBER and not _neighbours_have_a_number(tokens, match):
            continue
        found.append(_from_match("date", text, match))
    for pattern in _DATE_RES:
        for match in pattern.finditer(normalized):
            found.append(
                Signal(kind="date", term="numeric_date", text=text[match.start() : match.end()], start=match.start(), end=match.end())
            )
    return tuple(sorted(found, key=lambda signal: signal.start))


def _time_signals(text: str, normalized: str, tokens: Sequence[Token], blocked: frozenset[int]) -> tuple[Signal, ...]:
    found = list(_signals("time", text, tokens, rules.TIME_TERMS, blocked=blocked))
    for pattern in _TIME_RES:
        for match in pattern.finditer(normalized):
            found.append(
                Signal(kind="time", term="clock_time", text=text[match.start() : match.end()], start=match.start(), end=match.end())
            )
    return tuple(sorted(found, key=lambda signal: signal.start))


def _url_signals(text: str) -> tuple[Signal, ...]:
    found: list[Signal] = []
    for match in URL_PATTERN.finditer(text):
        url = match.group().rstrip(_URL_TRAILING)
        if url:
            found.append(Signal(kind="url", term="url", text=url, start=match.start(), end=match.start() + len(url)))
    return tuple(found)


def _label_positions(normalized: str) -> dict[str, tuple[int, int]]:
    """Where each labelled field starts and ends, e.g. "آدرس:" -> value offsets.

    The first occurrence of a label wins, and a label only counts when the operator
    actually wrote a separator after it, which is what keeps an ordinary sentence
    containing "مکان" from being read as a labelled venue.
    """
    positions: dict[str, tuple[int, int]] = {}
    groups = (
        ("address", rules.ADDRESS_LABELS),
        ("venue", rules.VENUE_LABELS),
        ("date", rules.DATE_LABELS),
        ("price", rules.PRICE_LABELS),
        ("city", rules.CITY_LABELS),
    )
    separators = re.escape(rules.LABEL_SEPARATORS)
    for name, labels in groups:
        pattern = re.compile(
            r"(?:(?<=^)|(?<=\W))(?:" + "|".join(re.escape(normalize(label)) for label in labels) + r")\s*[" + separators + r"]\s*"
        )
        match = pattern.search(normalized)
        if match:
            positions[name] = (match.start(), match.end())
    return positions


def analyze(text: str) -> SignalSet:
    """Recognize every signal in one source text, retrospective evidence first."""
    normalized = normalize(text)
    tokens = tokenize(normalized)

    retrospective = _signals("retrospective", text, tokens, rules.RETROSPECTIVE_TERMS)
    claimed = _token_span(retrospective)

    attendance = _signals("attendance", text, tokens, rules.ATTENDANCE_TERMS, blocked=claimed)
    claimed |= _token_span(attendance)

    place_context = _signals("place_context", text, tokens, rules.PLACE_CONTEXT_TERMS, blocked=claimed)
    place_terms = _signals("place_term", text, tokens, rules.PLACE_TERMS, blocked=claimed)
    event_strong = _signals("event_strong", text, tokens, rules.EVENT_TERMS_STRONG, blocked=claimed)
    event_weak = _signals(
        "event_weak", text, tokens, rules.EVENT_TERMS_WEAK, blocked=claimed | _token_span(event_strong)
    )
    urls = _url_signals(text)
    registration = tuple(
        signal
        for signal in _signals("registration", text, tokens, rules.REGISTRATION_TERMS, blocked=claimed)
        if not any(url.start <= signal.start and signal.end <= url.end for url in urls)
    )
    prices = _signals("price", text, tokens, rules.PRICE_TERMS, blocked=claimed)

    temporal_blocked = claimed | _token_span(place_context)
    dates = _date_signals(text, normalized, tokens, temporal_blocked)
    times = _time_signals(text, normalized, tokens, temporal_blocked)

    # Words already doing another job in the sentence cannot also be part of a name.
    busy = (
        claimed
        | _token_span(place_context)
        | _token_span(dates)
        | _token_span(times)
        | _token_span(prices)
        | _token_span(registration)
    )

    labels = _label_positions(normalized)
    locations = tuple(
        Signal(kind="location", term=name, text=text[start:end], start=start, end=end)
        for name, (start, end) in sorted(labels.items(), key=lambda item: item[1][0])
        if name in ("address", "venue")
    )

    return SignalSet(
        text=text,
        normalized=normalized,
        tokens=tokens,
        language=detect_language(text),
        event_strong=event_strong,
        event_weak=event_weak,
        dates=dates,
        times=times,
        place_terms=place_terms,
        place_context=place_context,
        attendance=attendance,
        retrospective=retrospective,
        registration=registration,
        prices=prices,
        locations=locations,
        urls=urls,
        named_event=find_named(text, tokens, rules.NAMED_EVENT_HEAD_TERMS, kind="named_event", blocked=busy),
        named_place=find_named(
            text,
            tokens,
            rules.NAMED_PLACE_HEAD_TERMS,
            kind="named_place",
            blocked=busy,
            line_prefix_terms=rules.PLACE_NAME_PREFIX_TERMS,
        ),
        labels=labels,
    )


# --------------------------------------------------------------------------------------
# Named constructions
# --------------------------------------------------------------------------------------

# Vocabulary compared against folded tokens has to be folded too, or "آخر" in the
# rules would never match the "اخر" the tokenizer produces.
_DATE_TOKENS = frozenset(token for phrase in rules.DATE_TERMS for token in phrase_tokens(phrase))
_NAME_STOPWORDS = frozenset(normalize(word) for word in rules.NAME_STOPWORDS)
_FUNCTION_WORDS = frozenset(normalize(word) for word in rules.FUNCTION_WORDS)
CITY_TOKENS = frozenset(normalize(city) for city in rules.KNOWN_CITIES)


def _is_name_token(token: Token) -> bool:
    """Whether a word can be part of a proper name rather than a sentence.

    Conservative by design: a name token is not a grammatical continuation, not a
    date word, not a bare number, and not a single character.
    """
    value = token.text
    if len(value) < rules.MIN_NAME_TOKEN_LENGTH or value.isdigit():
        return False
    return value not in _NAME_STOPWORDS and value not in _DATE_TOKENS


def _quoted_name(text: str, after: int) -> tuple[int, int] | None:
    """A quoted title immediately following a head term, e.g. نمایشگاه «نام نمایشگاه»."""
    cursor = after
    while cursor < len(text) and text[cursor] in " \t‌":
        cursor += 1
    if cursor >= len(text):
        return None
    for opening, closing in rules.QUOTE_PAIRS:
        if text[cursor] != opening:
            continue
        end = text.find(closing, cursor + 1)
        if end > cursor + 1 and text[cursor + 1 : end].strip():
            return cursor, end + 1
    return None


def _is_line_initial(text: str, tokens: Sequence[Token], index: int) -> bool:
    """Whether a word opens its own line, the position a name is announced from."""
    line_start, _ = line_bounds(text, tokens[index].start)
    return index == 0 or tokens[index - 1].end <= line_start


def find_named(
    text: str,
    tokens: Sequence[Token],
    head_terms: tuple[str, ...],
    *,
    kind: str,
    blocked: frozenset[int] = frozenset(),
    line_prefix_terms: tuple[str, ...] = (),
) -> Signal | None:
    """The first defensible "<head term> <name>" construction, or None.

    Three things have to hold, and each one rules out a false positive seen in real
    captions. The head term must be that exact word, so "رویدادهای تهران" is not one
    named event. It must open its line, the way a caption announces something, so a
    term buried in prose ("... به رویداد علاقه داریم") names nothing. And the words
    after it must look like a name rather than the rest of a sentence, so
    "رویداد میتونید" and "رویداد جزو" are rejected by the centralized stopword list.
    An explicitly quoted name — نمایشگاه «نام نمایشگاه» — is accepted anywhere,
    because the quotation marks are the operator saying which words are the title.

    Anything else yields None: an unknown title is better than an invented one.
    """
    for match in find_phrases(tokens, _vocabulary(head_terms)):
        quoted = _quoted_name(text, tokens[match.last_token].end)
        if quoted is not None:
            start, end = quoted
            return Signal(
                kind=kind,
                term=match.phrase,
                text=text[match.start : end],
                start=match.start,
                end=end,
                first_token=match.first_token,
                last_token=match.last_token,
            )

        if not _is_line_initial(text, tokens, match.first_token) and not _has_allowed_line_prefix(
            text, tokens, match.first_token, line_prefix_terms
        ):
            continue

        name_end: int | None = None
        for offset in range(1, rules.MAX_NAME_TOKENS + 1):
            index = match.last_token + offset
            if index >= len(tokens) or index in blocked or not _is_name_token(tokens[index]):
                break
            if _crosses_a_boundary(text, tokens[index - 1].end, tokens[index].start):
                break
            name_end = tokens[index].end
        if name_end is not None:
            return Signal(
                kind=kind,
                term=match.phrase,
                text=text[match.start : name_end],
                start=match.start,
                end=name_end,
                first_token=match.first_token,
                last_token=match.last_token,
            )
    return None


def _has_allowed_line_prefix(
    text: str, tokens: Sequence[Token], index: int, prefix_terms: tuple[str, ...]
) -> bool:
    """Whether a recognized introduction is the whole prefix before a name head."""
    if not prefix_terms:
        return False
    line_start, _ = line_bounds(text, tokens[index].start)
    prefix = normalize(text[line_start : tokens[index].start]).strip(" \t‌:：–—-؛،,;")
    return prefix in {normalize(term) for term in prefix_terms}


def _crosses_a_boundary(text: str, previous_end: int, next_start: int) -> bool:
    """Whether punctuation or a line break separates two words, ending a name."""
    return any(char not in " \t‌" for char in text[previous_end:next_start])


def has_meaningful_content(text: str) -> bool:
    """Whether an observation carries anything worth classifying at all."""
    return _has_meaningful_content(text, _FUNCTION_WORDS)


__all__ = ["Signal", "SignalSet", "URL_PATTERN", "analyze", "find_named", "has_meaningful_content"]
