from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import DiscoveryType, DiscoveryUnit, EvidenceBundle, EvidenceFragment, EvidenceKind
from ..extraction import fields, rules
from ..extraction.rule_based import classify
from ..extraction.signals import SignalSet, analyze, has_meaningful_content
from ..extraction.text import normalize, phrase_tokens


class GroupingStrategy(Protocol):
    name: str

    def group(self, bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]: ...


def _equivalent(text: str) -> str:
    # No fuzzy word deletion: even a one-digit date/price change must survive.
    return ' '.join(normalize(text).split())


def _anchor(found: SignalSet) -> bool:
    return bool(found.named_event or found.named_place or classify(found)[0] is not DiscoveryType.OTHER)


def _support_line(text: str) -> bool:
    found = analyze(text)
    if not found.tokens:
        return False
    first = found.tokens[0].start
    # A label is only structural when it opens the line and has a value.
    if any(start <= first and text[end:].strip() for start, end in found.labels.values()):
        return True
    temporal = fields.source_date_text(found)
    if temporal and phrase_tokens(temporal) == phrase_tokens(text):
        return True
    if fields.price_text(found) and any(signal.start == first for signal in found.prices):
        return True
    if any(signal.start == first and signal.term in rules.OPENING_HOURS_TERMS
           for signal in found.place_context):
        return True
    # Registration wording must be tied to a URL; arbitrary prose stays separate.
    if fields.registration_url(found) and any(signal.start == first for signal in found.registration):
        remainder = text
        for signal in sorted(found.registration + found.urls, key=lambda item: item.start, reverse=True):
            remainder = remainder[:signal.start] + ' ' * (signal.end - signal.start) + remainder[signal.end:]
        return not has_meaningful_content(remainder)
    return False


@dataclass(frozen=True)
class _Profile:
    fragment: EvidenceFragment
    signals: SignalSet
    anchor: bool
    support: bool
    ambiguous: bool


def _profile(fragment: EvidenceFragment) -> _Profile:
    found = analyze(fragment.text)
    lines = [line for line in fragment.text.splitlines() if line.strip()]
    # Multiple named occurrences within one image cannot safely anchor more text.
    line_signals = [analyze(line) for line in lines]
    names = {_equivalent(part.named_event.text) for part in line_signals if part.named_event}
    places = {_equivalent(part.named_place.text) for part in line_signals if part.named_place}
    occurrences = {_equivalent(part.text) for part in line_signals
                   if classify(part)[0] is DiscoveryType.EVENT}
    ambiguous = len(names) > 1 or len(places) > 1 or len(occurrences) > 1
    anchor = _anchor(found) and not ambiguous
    support = not (
        anchor or ambiguous or found.event_strong or found.event_weak
        or found.place_terms or found.retrospective or found.attendance
    ) and bool(lines) and all(_support_line(line) for line in lines)
    return _Profile(fragment, found, anchor, support, ambiguous)


def _conflicts(first: _Profile, second: _Profile) -> bool:
    a, b = first.signals, second.signals
    # Compare source wording only; no date, price, or address normalization here.
    # Unequal temporal descriptions can be complementary, but v1 abstains.
    for reader in (fields.source_date_text, fields.address, fields.venue_name,
                   fields.city, fields.price_text, fields.registration_url,
                   fields.opening_hours_text):
        left, right = reader(a), reader(b)
        if left and right and _equivalent(left) != _equivalent(right):
            return True
    return False


def _adjacent(first: EvidenceFragment, second: EvidenceFragment) -> bool:
    if first.kind is not second.kind:
        return False
    if first.kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
        return second.slide_index == first.slide_index + 1
    # Adjacent *stored* samples only; unavailable observations reset the chain.
    return first.kind is EvidenceKind.REEL_FRAME_OCR


class ConservativeGrouping:
    '''Precision-first segmentation; never classify concatenations to decide merges.'''

    name = 'conservative/1'

    def group(self, bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]:
        caption: _Profile | None = None
        groups: list[list[_Profile]] = []
        current: list[_Profile] | None = None
        previous: EvidenceFragment | None = None
        for fragment in bundle.fragments:
            if not fragment.meaningful or not has_meaningful_content(fragment.text):
                current = None
                previous = None
                continue
            profile = _profile(fragment)
            if fragment.kind is EvidenceKind.CAPTION:
                caption = profile
                continue
            adjacent = previous is not None and _adjacent(previous, fragment)
            repeated = (
                adjacent and current is not None
                and fragment.kind is EvidenceKind.REEL_FRAME_OCR
                and _equivalent(fragment.text) == _equivalent(current[-1].fragment.text)
            )
            support = (
                adjacent and current is not None and current[0].anchor and profile.support
                and not any(_conflicts(prior, profile) for prior in current)
            )
            if repeated or support:
                current.append(profile)
            else:
                current = [profile]
                groups.append(current)
            previous = fragment

        if caption is not None:
            if len(groups) == 1 and self._caption_compatible(caption, groups[0]):
                groups[0].insert(0, caption)
            else:
                groups.insert(0, [caption])
        return tuple(
            DiscoveryUnit.from_fragments(
                tuple(profile.fragment for profile in group), strategy=self.name
            ) for group in groups
        )

    @staticmethod
    def _caption_compatible(caption: _Profile, group: list[_Profile]) -> bool:
        if caption.ambiguous or any(part.ambiguous or _conflicts(caption, part) for part in group):
            return False
        if all(_equivalent(caption.fragment.text) == _equivalent(part.fragment.text) for part in group):
            return True
        # Same post / a single group alone is not proof of a shared occurrence.
        return (caption.anchor and all(part.support for part in group)) or (
            caption.support and group[0].anchor
        )
