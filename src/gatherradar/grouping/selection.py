from __future__ import annotations

from collections.abc import Iterable

from ..domain import EvidenceBundle, EvidenceFragment, EvidenceKind, RawItem


def select_semantic_evidence(
    raw_item: RawItem, history: Iterable[EvidenceFragment]
) -> EvidenceBundle:
    '''Latest stored version per semantic slot, with a fresh current caption.

    Input order is storage append order, NOT bundle sort order. Failed/empty
    versions replace earlier successes too; grouping decides semantic eligibility.
    There is no run manifest, tombstone, or re-observation timestamp in Stage 4.
    This is therefore a latest-known-slot view, not a complete media-run snapshot.
    '''
    latest: dict[tuple[EvidenceKind, int | str | None], EvidenceFragment] = {}
    for fragment in history:
        if fragment.raw_item_id != raw_item.id or fragment.kind is EvidenceKind.CAPTION:
            continue
        position: int | str | None = None
        if fragment.kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
            position = fragment.slide_index
        elif fragment.kind is EvidenceKind.REEL_FRAME_OCR:
            position = fragment.frame_timestamp_ms
        elif fragment.kind is EvidenceKind.WEBSITE_TEXT:
            # One text slot per page URL; section identities need a future contract.
            position = fragment.source_url
        latest[fragment.kind, position] = fragment
    return EvidenceBundle.from_raw_item(raw_item, tuple(latest.values()))
