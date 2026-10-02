from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ..domain import DiscoveryType, DiscoveryUnit, EvidenceBundle, EvidenceFragment, EvidenceKind
from ..extraction import fields, rules
from ..extraction.rule_based import classify
from ..extraction.signals import SignalSet, analyze, has_meaningful_content
from ..extraction.text import normalize, phrase_tokens, title_equivalence_key

# Debug explanations carried on `DiscoveryUnit.notes`; never persisted or exported.
NOTE_SUPPORT_ATTACHED = 'support_attached_to_anchor'
NOTE_REPEATED_ANCHOR = 'repeated_anchor_collapsed'
NOTE_INSUFFICIENT_OCR = 'ocr_fragment_insufficient_for_independent_event'

_MEDIA_OCR = frozenset({EvidenceKind.IMAGE_OCR, EvidenceKind.CAROUSEL_SLIDE_OCR, EvidenceKind.REEL_FRAME_OCR})
# An unlabelled clock or numeric date alone on its OCR line ("3 am", "18:30", "9/25").
# Without a label, month or weekday it cannot be told apart from OCR noise.
_ISOLATED_TEMPORAL = re.compile(
    r'[^\w]*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,4}[/\-]\d{1,2}(?:[/\-]\d{1,4})?)[^\w]*'
)


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
    lines: tuple[str, ...]
    # Kind-tagged equivalence key of the fragment's single named title, if it anchors.
    title: tuple[str, ...] | None
    # Media OCR holding only isolated clock/numeric-date lines: never support text.
    insufficient: bool


def _profile(fragment: EvidenceFragment) -> _Profile:
    found = analyze(fragment.text)
    lines = tuple(line for line in fragment.text.splitlines() if line.strip())
    # Multiple named occurrences within one image cannot safely anchor more text.
    line_signals = [analyze(line) for line in lines]
    names = {_equivalent(part.named_event.text) for part in line_signals if part.named_event}
    places = {_equivalent(part.named_place.text) for part in line_signals if part.named_place}
    occurrences = {_equivalent(part.text) for part in line_signals
                   if classify(part)[0] is DiscoveryType.EVENT}
    ambiguous = len(names) > 1 or len(places) > 1 or len(occurrences) > 1
    anchor = _anchor(found) and not ambiguous
    insufficient = fragment.kind in _MEDIA_OCR and all(
        _weak_temporal(line) for line in lines if has_meaningful_content(line))
    support = not (
        anchor or ambiguous or insufficient or found.event_strong or found.event_weak
        or found.place_terms or found.retrospective or found.attendance
    ) and bool(lines) and all(_support_line(line) for line in lines)
    named = found.named_event or found.named_place
    title = None
    if anchor and named is not None:
        title = ('event' if found.named_event else 'place', *_title_words(found, named.start, named.end))
    return _Profile(fragment, found, anchor, support, ambiguous, lines, title, insufficient)


def _title_words(found: SignalSet, start: int, end: int) -> tuple[str, ...]:
    '''Folded title words plus numbers written directly after them on the same line.

    A named construction never contains a bare number, but "کارگاه سفال ۱" and
    "کارگاه سفال ۲" are different occurrences, so trailing numbers stay significant.
    '''
    words = list(title_equivalence_key(found.text[start:end]))
    for token in found.tokens:
        if token.start < end:
            continue
        if not token.text.isdigit() or any(char not in ' \t\u200c' for char in found.text[end:token.start]):
            break
        words.append(token.text)
        end = token.end
    return tuple(words)


def _weak_temporal(line: str) -> bool:
    return bool(_ISOLATED_TEMPORAL.fullmatch(normalize(line).strip()))


def _temporal_conflict(a: SignalSet, b: SignalSet) -> bool:
    left, right = fields.source_date_text(a), fields.source_date_text(b)
    if not (left and right) or _equivalent(left) == _equivalent(right):
        return False
    # Date-only wording and clock-only wording describe different components of
    # one occurrence; any other unequal pair abstains.
    return not ((a.dates and not a.times and b.times and not b.dates)
                or (b.dates and not b.times and a.times and not a.dates))


def _conflicts(first: _Profile, second: _Profile) -> bool:
    a, b = first.signals, second.signals
    if _temporal_conflict(a, b):
        return True
    # Compare source wording only; no date, price, or address normalization here.
    for reader in (fields.address, fields.venue_name, fields.city, fields.price_text,
                   fields.registration_url, fields.opening_hours_text):
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


def _title_line(line: str, title: tuple[str, ...]) -> bool:
    '''The whole title, or an exact contiguous run of at least two of its words.'''
    words = title_equivalence_key(line)
    if not words or len(words) > len(title):
        return False
    if words == title:
        return True
    return len(words) >= 2 and any(
        title[start:start + len(words)] == words for start in range(len(title) - len(words) + 1)
    )


def _states_no_fact(text: str) -> bool:
    '''Whether text carries nothing discovery could read or anchor on.'''
    found = analyze(text)
    return not (found.positive or found.named_event or found.named_place or found.urls
                or found.labels or found.retrospective
                or fields.city(found) or fields.venue_name(found))


def _relation(profile: _Profile, title: tuple[str, ...]) -> tuple[bool, str] | None:
    '''How a media fragment relates to an anchor with `title`, or None.

    (True, note): it only repeats the anchor title, plus at most text that states no
    fact or isolated clock/numeric-date OCR lines. Provenance only, no text.
    (False, note): it repeats the title and otherwise holds only supporting lines;
    its text may join the anchor after the usual conflict checks.
    '''
    if profile.ambiguous or profile.fragment.kind not in _MEDIA_OCR:
        return None
    if profile.title is not None and profile.title != title:
        return None  # A different named occurrence.
    words = title[1:]
    residual = [line for line in profile.lines if not _title_line(line, words)]
    if len(residual) == len(profile.lines):
        return None  # The title is not repeated at all.
    meaningful = [line for line in residual if has_meaningful_content(line)]
    weak = [line for line in meaningful if _weak_temporal(line)]
    rest = [line for line in meaningful if line not in weak]
    if not rest or _states_no_fact('\n'.join(rest)):
        return True, NOTE_INSUFFICIENT_OCR if weak else NOTE_REPEATED_ANCHOR
    if profile.title is not None and all(_support_line(line) for line in rest):
        return False, NOTE_SUPPORT_ATTACHED
    return None


@dataclass
class _Group:
    members: list[_Profile]
    collapsed: list[EvidenceFragment] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def title(self) -> tuple[str, ...] | None:
        return self.members[0].title

    def admit(self, profile: _Profile, title: tuple[str, ...]) -> bool:
        '''Attach a repetition of this group's anchor; False leaves the group unchanged.'''
        relation = _relation(profile, title)
        if relation is None:
            return False
        collapse, note = relation
        if collapse:
            self.collapsed.append(profile.fragment)
        elif any(_conflicts(member, profile) for member in self.members):
            return False
        else:
            self.members.append(profile)
        self.notes.append((profile.fragment.fragment_id, note))
        return True


class ConservativeGrouping:
    '''Precision-first segmentation; never classify concatenations to decide merges.

    Version 2 adds same-occurrence handling within one RawItem: a media fragment
    that repeats an anchor's exact (folded) title, with no conflicting facts,
    joins that anchor instead of becoming a parallel candidate.
    '''

    name = 'conservative/2'

    def group(self, bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]:
        caption: _Profile | None = None
        listing: list[_Profile] = []
        groups: list[_Group] = []
        current: _Group | None = None
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
            if fragment.kind is EvidenceKind.WEBSITE_LISTING:
                listing.append(profile)
                continue
            adjacent = previous is not None and _adjacent(previous, fragment)
            if profile.insufficient and adjacent and current is not None and current.members[0].anchor:
                # Kept as provenance of the neighbouring anchor; it is not a fact.
                current.collapsed.append(fragment)
                current.notes.append((fragment.fragment_id, NOTE_INSUFFICIENT_OCR))
                previous = fragment
                continue
            repeated = (
                adjacent and current is not None
                and fragment.kind is EvidenceKind.REEL_FRAME_OCR
                and _equivalent(fragment.text) == _equivalent(current.members[-1].fragment.text)
            )
            support = (
                adjacent and current is not None and current.members[0].anchor and profile.support
                and not any(_conflicts(prior, profile) for prior in current.members)
            )
            if repeated or support:
                current.members.append(profile)
                if not repeated:
                    current.notes.append((fragment.fragment_id, NOTE_SUPPORT_ATTACHED))
            else:
                # The most recent earlier anchor with the same title, if it admits this.
                target = next((group for group in reversed(groups)
                               if group.title is not None and group.admit(profile, group.title)), None)
                if target is not None:
                    current = target
                else:
                    current = _Group([profile])
                    groups.append(current)
            previous = fragment

        if caption is not None:
            lead = _Group([caption])
            absorbed = False
            if caption.title is not None:
                for group in list(groups):
                    if self._absorb(lead, group, caption.title):
                        groups.remove(group)
                        absorbed = True
            if absorbed:
                groups.insert(0, lead)
            elif len(groups) == 1 and self._caption_compatible(caption, groups[0].members):
                groups[0].members.insert(0, caption)
            else:
                groups.insert(0, lead)
        # A listing card was selected by the exact detail link, so it describes
        # the same item as that page. It joins the page unit; field-level
        # disagreement is detected by discovery, never resolved here.
        pages = [group for group in groups
                 if any(p.fragment.kind is EvidenceKind.WEBSITE_TEXT for p in group.members)]
        if listing and len(pages) == 1:
            pages[0].members.extend(listing)
        elif listing:
            groups.append(_Group(listing))
        return tuple(
            DiscoveryUnit.from_fragments(
                tuple(profile.fragment for profile in group.members), strategy=self.name,
                collapsed=tuple(group.collapsed), notes=tuple(group.notes),
            ) for group in groups
        )

    @staticmethod
    def _absorb(lead: _Group, group: _Group, title: tuple[str, ...]) -> bool:
        '''Merge a media group that repeats the caption anchor, all or nothing.

        Its first member must repeat the caption title; supporting members must not
        conflict with anything already in the caption unit. Same post alone is never
        enough: a group led by a different title or by unrelated text stays apart.
        '''
        if _relation(group.members[0], title) is None:
            return False
        trial = _Group(list(lead.members), list(lead.collapsed), list(lead.notes))
        for index, member in enumerate(group.members):
            if trial.admit(member, title):
                continue
            # Members the chain attached as support keep their place if compatible.
            if index == 0 or not member.support or any(_conflicts(prior, member) for prior in trial.members):
                return False
            trial.members.append(member)
        trial.collapsed.extend(group.collapsed)
        trial.notes.extend(note for note in group.notes
                           if note not in trial.notes)
        lead.members, lead.collapsed, lead.notes = trial.members, trial.collapsed, trial.notes
        return True

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
