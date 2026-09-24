from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .raw_item import RawItem


class EvidenceKind(StrEnum):
    CAPTION = 'caption'
    IMAGE_OCR = 'image_ocr'
    CAROUSEL_SLIDE_OCR = 'carousel_slide_ocr'
    REEL_FRAME_OCR = 'reel_frame_ocr'
    WEBSITE_TEXT = 'website_text'


def _digest(*parts: object) -> str:
    payload = '\x1f'.join('' if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceFragment:
    '''One source-supported piece of text with its extraction provenance.'''

    fragment_id: str
    raw_item_id: str
    kind: EvidenceKind
    text: str
    source_url: str | None = None
    local_asset_path: str | None = None
    asset_hash: str | None = None
    slide_index: int | None = None
    frame_timestamp_ms: int | None = None
    extraction_engine: str | None = None
    extraction_version: str | None = None
    extraction_config: str | None = None
    raw_text: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.fragment_id.strip() or not self.raw_item_id.strip():
            raise ValueError('fragment_id and raw_item_id must not be empty')
        for name, required_kind in (
            ('slide_index', EvidenceKind.CAROUSEL_SLIDE_OCR),
            ('frame_timestamp_ms', EvidenceKind.REEL_FRAME_OCR),
        ):
            value = getattr(self, name)
            if self.kind is required_kind:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f'{required_kind.value} requires a non-negative integer {name}')
            elif value is not None:
                raise ValueError(f'{name} is only valid for {required_kind.value}')

    @property
    def meaningful(self) -> bool:
        return bool(self.text.strip()) and self.failure_reason is None

    @property
    def sort_key(self) -> tuple[int, int, str]:
        order = {kind: index for index, kind in enumerate(EvidenceKind)}
        position = self.slide_index
        if position is None:
            position = self.frame_timestamp_ms if self.frame_timestamp_ms is not None else -1
        return order[self.kind], position, self.fragment_id

    @classmethod
    def create(
        cls, *, raw_item_id: str, kind: EvidenceKind, text: str,
        source_url: str | None = None, local_asset_path: str | Path | None = None,
        asset_hash: str | None = None, slide_index: int | None = None,
        frame_timestamp_ms: int | None = None, extraction_engine: str | None = None,
        extraction_version: str | None = None, extraction_config: str | None = None,
        raw_text: str | None = None, failure_reason: str | None = None,
    ) -> EvidenceFragment:
        path = str(local_asset_path) if local_asset_path is not None else None
        fragment_id = 'evidence:' + _digest(
            raw_item_id, kind.value, slide_index, frame_timestamp_ms, asset_hash,
            extraction_engine, extraction_version, extraction_config, raw_text, text,
            failure_reason,
        )
        return cls(
            fragment_id=fragment_id, raw_item_id=raw_item_id, kind=kind, text=text,
            source_url=source_url, local_asset_path=path, asset_hash=asset_hash,
            slide_index=slide_index, frame_timestamp_ms=frame_timestamp_ms,
            extraction_engine=extraction_engine, extraction_version=extraction_version,
            extraction_config=extraction_config, raw_text=raw_text,
            failure_reason=failure_reason,
        )


def caption_fragment(raw_item: RawItem) -> EvidenceFragment:
    return EvidenceFragment.create(
        raw_item_id=raw_item.id, kind=EvidenceKind.CAPTION,
        text=raw_item.raw_text, raw_text=raw_item.raw_text,
        source_url=raw_item.content_url, asset_hash=raw_item.content_hash,
    )


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    raw_item_id: str
    fragments: tuple[EvidenceFragment, ...] = ()

    def __post_init__(self) -> None:
        if not self.raw_item_id.strip():
            raise ValueError('raw_item_id must not be empty')
        if any(fragment.raw_item_id != self.raw_item_id for fragment in self.fragments):
            raise ValueError('every fragment must belong to the bundle raw_item_id')
        ordered = tuple(sorted(self.fragments, key=lambda item: item.sort_key))
        object.__setattr__(self, 'fragments', ordered)

    @classmethod
    def from_raw_item(
        cls, raw_item: RawItem, extra_fragments: tuple[EvidenceFragment, ...] = ()
    ) -> EvidenceBundle:
        return cls(raw_item.id, (caption_fragment(raw_item), *extra_fragments))


@dataclass(frozen=True, slots=True)
class DiscoveryUnit:
    '''An explicit group; multiple units may belong to one evidence bundle.'''

    unit_id: str
    raw_item_id: str
    text: str
    fragments: tuple[EvidenceFragment, ...]

    def __post_init__(self) -> None:
        if not self.unit_id.strip() or not self.raw_item_id.strip():
            raise ValueError('unit_id and raw_item_id must not be empty')
        if not self.fragments:
            raise ValueError('a DiscoveryUnit must contain at least one fragment')
        if any(fragment.raw_item_id != self.raw_item_id for fragment in self.fragments):
            raise ValueError('every fragment must belong to the unit raw_item_id')

    @classmethod
    def from_fragment(cls, fragment: EvidenceFragment) -> DiscoveryUnit:
        return cls(
            unit_id='unit:' + _digest(fragment.raw_item_id, fragment.fragment_id),
            raw_item_id=fragment.raw_item_id, text=fragment.text,
            fragments=(fragment,),
        )


def caption_discovery_units(bundle: EvidenceBundle) -> tuple[DiscoveryUnit, ...]:
    caption = next(
        (item for item in bundle.fragments if item.kind is EvidenceKind.CAPTION), None
    )
    return (DiscoveryUnit.from_fragment(caption),) if caption is not None else ()


__all__ = [
    'DiscoveryUnit', 'EvidenceBundle', 'EvidenceFragment', 'EvidenceKind',
    'caption_discovery_units', 'caption_fragment',
]
