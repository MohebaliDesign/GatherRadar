"""Reusable manual application service: acquire or reuse, analyze, then snapshot."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..config import load_sources
from ..collectors.base import safe_failure
from ..domain import SourceType
from ..review.models import ReviewError, SnapshotRepository, SnapshotResult
from ..review.serialization import review_window
from ..review.io import atomic_json
from .canonicalization_run import run_canonical_review
from .collection_run import run_instagram_collection
from .website_run import run_website_collection
from .evidence_run import run_instagram_evidence

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceRun:
    source_id: str
    observed_item_ids: tuple[str, ...] = ()
    status: str = 'success'
    failures: tuple[str, ...] = ()
    new: int = 0
    changed: int = 0
    existing: int = 0


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    started_at: str
    finished_at: str | None
    selected_source_ids: tuple[str, ...]
    sources: tuple[SourceRun, ...]
    limit: int
    days: int
    review_timezone: str
    evidence_mode: str
    mode: str
    status: str


@dataclass(frozen=True)
class RefreshResult:
    snapshot: SnapshotResult
    sources: tuple[SourceRun, ...]
    output_paths: tuple[Path, ...] = ()
    export_failures: tuple[str, ...] = ()
    import_summary: object | None = None


class RefreshService:
    def __init__(self, repository: SnapshotRepository, *,
                 website_collect: Callable = run_website_collection,
                 instagram_collect: Callable = run_instagram_collection,
                 acquire_evidence: Callable = run_instagram_evidence,
                 analyze: Callable = run_canonical_review,
                 now: Callable[[], datetime] | None = None,
                 import_reviews: Callable | None = None, export_reviews: Callable | None = None) -> None:
        self.repository = repository
        self.website_collect = website_collect
        self.instagram_collect = instagram_collect
        self.acquire_evidence = acquire_evidence
        self.analyze = analyze
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.import_reviews = import_reviews
        self.export_reviews = export_reviews

    def run(self, source_ids: tuple[str, ...] = (), *, all_enabled: bool = False,
            config_path: str | Path = 'config/sources.yaml', data_dir: str | Path = 'data',
            limit: int = 5, days: int = 14, review_timezone: str = 'Asia/Tehran',
            skip_instagram_evidence: bool = False, collect: bool = True,
            run_id: str | None = None) -> RefreshResult:
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError('limit must be between 1 and 30 per source')
        if type(days) is not int or not 1 <= days <= 90:
            raise ValueError('days must be between 1 and 90')
        ZoneInfo(review_timezone)
        if bool(source_ids) == all_enabled:
            raise ValueError('select source IDs or all-enabled, exclusively')
        sources = load_sources(config_path)
        if set(source_ids) - {s.id for s in sources}:
            raise ValueError('unknown source selection')
        selected = sorted((s for s in sources if (s.enabled if all_enabled else s.id in source_ids)), key=lambda s: s.id)
        if not selected or (collect and any(not s.enabled for s in selected)):
            raise ValueError('refresh requires approved enabled sources')
        run_id = run_id or uuid4().hex
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
            raise ValueError('run ID must contain 1–64 filename-safe characters')
        with self.repository.state.lock():
            # Check persistence and import supported human edits before acquisition.
            imported = self.import_reviews() if self.import_reviews else None
            prior = self.repository.find_run(run_id)
            if prior:
                paths, errors = self._export(run_id)
                return RefreshResult(prior, (), paths, errors, imported)
            started = self.now()
            if started.tzinfo is None or started.utcoffset() is None:
                raise ValueError('run clock must be timezone-aware')
            path = Path(data_dir) / 'runs' / f'{run_id}.json'
            mode = 'refresh' if collect else 'stored_sync'
            evidence_mode = 'caption_only' if skip_instagram_evidence else 'stored_or_acquired_media'
            ids = tuple(s.id for s in selected)
            if path.exists():
                try:
                    old = json.loads(path.read_text(encoding='utf-8'))
                    if (old['mode'], old['selected_source_ids'], old['limit'], old['days'],
                            old['review_timezone'], old['evidence_mode']) != (
                            mode, list(ids), limit, days, review_timezone, evidence_mode):
                        raise ValueError
                    started = datetime.fromisoformat(old['started_at'])
                    if started.tzinfo is None or started.utcoffset() is None:
                        raise ValueError
                except (ValueError, KeyError, TypeError):
                    raise ReviewError('Existing run manifest is incompatible; use a new run ID for a different invocation.') from None
            reports: list[SourceRun] = []

            def save(status: str, finished: datetime | None = None) -> None:
                atomic_json(path, asdict(RunManifest(run_id, started.isoformat(),
                    finished.isoformat() if finished else None, ids, tuple(reports), limit, days,
                    review_timezone, evidence_mode, mode, status)))

            save('running')
            observed = {} if collect else None
            if collect:
                for source in selected:
                    LOGGER.info('source_collection_started', extra={'run_id': run_id, 'source_id': source.id})
                    try:
                        collector = self.website_collect if source.source_type is SourceType.WEBSITE else self.instagram_collect
                        summary = collector(source.id, config_path=config_path, data_dir=data_dir, limit=limit)
                        items = summary.observed_items
                        if (len(items) > limit or len({i.id for i in items}) != len(items)
                                or any(i.source_id != source.id or i.source_type != source.source_type for i in items)):
                            raise ValueError('invalid collection membership')
                        observed[source.id] = items
                        failures = ['collection_item_failed'] if summary.failed else []
                        if source.source_type is SourceType.INSTAGRAM and not skip_instagram_evidence and items:
                            try:
                                evidence = self.acquire_evidence(source.id, config_path=config_path,
                                    data_dir=data_dir, limit=limit, observed_items=items)
                                if evidence.failures or evidence.malformed:
                                    failures.append('media_evidence_partial')
                            except Exception:
                                failures.append('media_evidence_failed_caption_available')
                        reports.append(SourceRun(source.id, summary.observed_item_ids,
                            'partial' if failures else 'success', tuple(failures),
                            summary.new, summary.changed, summary.already_existing))
                    except Exception as exc:
                        observed[source.id] = ()
                        reports.append(SourceRun(source.id, status='failed', failures=('source_collection_failed', safe_failure(exc))))
                    LOGGER.info('source_collection_finished', extra={'run_id': run_id,
                        'source_id': source.id, 'status': reports[-1].status})
                    save('running')
            try:
                review = self.analyze(ids, config_path=config_path, data_dir=data_dir, limit=limit,
                    instagram_evidence=not skip_instagram_evidence, observed_items=observed)
                existing = {r.source_id: r for r in reports}
                for source in review.sources:
                    prior_source = existing.get(source.source.id, SourceRun(source.source.id))
                    errors = list(prior_source.failures)
                    if source.path_used == 'source_failed':
                        errors.append('analysis_failed')
                    if source.diagnostics:
                        errors.append('analysis_diagnostics')
                    status = 'failed' if source.path_used == 'source_failed' or prior_source.status == 'failed' else ('partial' if errors else prior_source.status)
                    if not collect and source.path_used == 'no_local_data':
                        errors.append('no_local_data')
                        status = 'partial'
                    member_ids = prior_source.observed_item_ids if collect else source.observed_item_ids
                    existing[source.source.id] = SourceRun(source.source.id, member_ids,
                        status, tuple(errors), prior_source.new, prior_source.changed, prior_source.existing)
                reports = [existing[s.id] for s in selected]
                failures = tuple(f'{r.source_id}:{error}' for r in reports for error in r.failures)
                if review.result.rejected or review.result.diagnostics:
                    failures += ('canonicalization:diagnostics',)
                status = ('failed' if all(r.status == 'failed' for r in reports)
                          else 'partial' if failures else 'success')
                window = review_window(review.result.events, started, days, review_timezone)
                finished = self.now()
                save('syncing', finished)
                snapshot = self.repository.sync(review.result, window, run_id=run_id,
                    started_at=started, finished_at=finished, days=days, review_timezone=review_timezone,
                    source_count=len(selected), failures=failures, status=status,
                    run_metadata={'selected_source_ids': ids, 'sources': [asdict(r) for r in reports],
                                  'limit': limit, 'mode': mode, 'evidence_mode': evidence_mode})
                save(status, finished)
                paths, errors = self._export(run_id)
                return RefreshResult(snapshot, tuple(reports), paths, errors, imported)
            except Exception:
                save('failed_or_unconfirmed', self.now())
                raise

    def _export(self, run_id: str) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        if self.export_reviews is None:
            return (), ()
        try:
            return self.export_reviews(run_id)
        except Exception:
            return (), ('Export failed after persistence; retry offline export for this run ID.',)
