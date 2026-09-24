"""Read one local snapshot per source, discover, normalize, then canonicalize."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import load_sources
from ..deduplication import CandidateContext, CanonicalizationResult, canonicalize
from ..domain import DiscoveryUnit, EvidenceKind, Source, SourceType
from ..extraction import DiscoveryService, RuleBasedDiscoveryProvider
from ..storage import JsonlEvidenceStore, JsonlRawItemStore
from .collection_run import instagram_output_path
from .discovery_run import run_discovery, select_latest
from .evidence_discovery_run import run_evidence_discovery
from .evidence_paths import instagram_evidence_output_path
from .normalization_run import run_normalization
from .website_run import website_output_path


@dataclass(frozen=True, slots=True)
class SourceReview:
    source: Source
    path_used: str
    raw_items: int = 0
    event_candidates: int = 0
    place_candidates: int = 0
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalReview:
    result: CanonicalizationResult
    sources: tuple[SourceReview, ...]


def identity_slot(unit: DiscoveryUnit | None) -> str:
    if unit is None or any(f.kind in {EvidenceKind.CAPTION, EvidenceKind.WEBSITE_TEXT} for f in unit.fragments):
        return "primary"
    # Stage 5 orders fragments deterministically by kind/position. Using the
    # first slot keeps an edit to its content from changing occurrence identity.
    fragment = unit.fragments[0]
    position = fragment.slide_index if fragment.kind is EvidenceKind.CAROUSEL_SLIDE_OCR else fragment.frame_timestamp_ms
    return f"{fragment.kind.value}:{position if position is not None else 'single'}"


def run_canonical_review(
    source_ids: Sequence[str] = (), *, all_enabled: bool = False,
    config_path: str | Path = "config/sources.yaml", data_dir: str | Path = "data",
    limit: int = 5, instagram_evidence: bool = False,
) -> CanonicalReview:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise ValueError("limit must be between 1 and 30 per source")
    if bool(source_ids) == all_enabled:
        raise ValueError("select source IDs or all_enabled, exclusively")
    sources = load_sources(config_path)
    known = {s.id for s in sources}
    if set(source_ids) - known:
        raise ValueError("unknown source selection")
    selected = sorted((s for s in sources if (s.enabled if all_enabled else s.id in source_ids)), key=lambda s: s.id)
    contexts, reports = [], []
    service = DiscoveryService(RuleBasedDiscoveryProvider())
    for source in selected:
        try:
            path = (website_output_path(source, data_dir) if source.source_type is SourceType.WEBSITE
                    else instagram_output_path(source, data_dir))
            stored = JsonlRawItemStore(path).read_latest_items()
            diagnostics = [f"raw:{reason.split(':', 1)[0]}:invalid_record" for reason in stored.malformed]
            items = tuple(item for item in stored.items if item.source_id == source.id and item.source_type == source.source_type)
            if len(items) != len(stored.items):
                diagnostics.append("raw:context_mismatch")
            items = items[:limit] if source.source_type is SourceType.WEBSITE else select_latest(items, limit)
            if not items:
                reports.append(SourceReview(source, "no_local_data", diagnostics=tuple(diagnostics)))
                continue
            history = ()
            if source.source_type is SourceType.INSTAGRAM and instagram_evidence:
                evidence = JsonlEvidenceStore(instagram_evidence_output_path(source, data_dir)).read()
                history = evidence.fragments
                diagnostics.extend(f"evidence:{reason.split(':', 1)[0]}:invalid_record" for reason in evidence.malformed)
            # Evidence opt-in always uses Stage 5 for this source. Its primary
            # fragment is the caption fallback, including items without media.
            use_units = source.source_type is SourceType.WEBSITE or instagram_evidence
            if use_units:
                summary = run_evidence_discovery(items, history, service, sources={source.id: source})
                units = {unit.unit_id: unit for item in summary.items for unit in item.units}
                if source.source_type is SourceType.WEBSITE:
                    mode = "website_text"
                else:
                    used_media = any(f.kind not in {EvidenceKind.CAPTION, EvidenceKind.WEBSITE_TEXT}
                                     for unit in units.values() for f in unit.fragments)
                    mode = "evidence_with_caption_fallback" if used_media else "caption_fallback"
            else:
                summary = run_discovery(items, service, sources={source.id: source})
                units = {}
                mode = "caption_only"
            if summary.failed:
                diagnostics.append(f"discovery_failed:{summary.failed}")
            raw_map = {item.id: item for item in items}
            normalized = run_normalization(summary.outcomes, raw_map, {source.id: source},
                                           unit_texts={key: unit.text for key, unit in units.items()})
            discoveries = [o for o in summary.outcomes if o.candidate is not None]
            first_seen = dict(stored.first_seen_at)
            source_contexts = []
            for outcome, discovery in zip(normalized, discoveries):
                raw = raw_map[outcome.candidate.raw_item_id]
                source_contexts.append(CandidateContext(outcome, discovery.candidate, raw, source,
                    first_seen[raw.id], identity_slot(units.get(discovery.discovery_unit_id))))
            contexts.extend(source_contexts)
            reports.append(SourceReview(source, mode, len(items), summary.events, summary.places, tuple(diagnostics)))
        except Exception:
            # Never echo an exception that could contain source payloads or secrets.
            reports.append(SourceReview(source, "source_failed", diagnostics=("offline_source_failed",)))
    return CanonicalReview(canonicalize(contexts), tuple(reports))
