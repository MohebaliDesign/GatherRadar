"""Reusable manual application service: acquire or reuse, analyze, then snapshot."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..acquisition.coverage import publisher_coverage, with_channel_gaps
from ..acquisition.models import DELIBERATE, ChannelResult, ChannelStatus, PublisherCoverage
from ..acquisition.strategies import AcquisitionStrategy, LinkedPageStrategy, default_strategies, strategy_for
from ..config import load_sources
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
    channel_status: str = 'success'


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
    channels: tuple[ChannelResult, ...] = ()
    publishers: tuple[PublisherCoverage, ...] = ()
    policy_notices: tuple = ()


class RefreshService:
    def __init__(self, repository: SnapshotRepository, *,
                 website_collect: Callable = run_website_collection,
                 instagram_collect: Callable = run_instagram_collection,
                 acquire_evidence: Callable = run_instagram_evidence,
                 analyze: Callable = run_canonical_review,
                 now: Callable[[], datetime] | None = None,
                 import_reviews: Callable | None = None, export_reviews: Callable | None = None,
                 strategies: tuple[AcquisitionStrategy, ...] | None = None,
                 linked: LinkedPageStrategy | None = None, policy_check: Callable | None = None) -> None:
        self.repository = repository
        # Channel strategies are chosen per Source by capability, never by
        # publisher. Linked pages and policy re-checks are opt-in network
        # features wired by the application entry point.
        self.website_collect = website_collect
        self.instagram_collect = instagram_collect
        self.strategies = strategies or default_strategies(
            lambda *a, **k: self.website_collect(*a, **k), lambda *a, **k: self.instagram_collect(*a, **k))
        self.linked = linked
        self.policy_check = policy_check
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
            channels: list[ChannelResult] = []
            # Deliberately disabled channels of the selected publishers are
            # reported from configuration only; they are never contacted.
            publishers = {s.publisher_key for s in selected}
            peers = [s for s in sorted(sources, key=lambda s: s.id)
                     if not s.enabled and s.publisher_key in publishers]
            notices = ()
            if collect:
                for source in selected:
                    LOGGER.info('source_collection_started', extra={'run_id': run_id, 'source_id': source.id})
                    strategy = strategy_for(source, self.strategies)
                    if strategy is None:
                        result = ChannelResult(source.id, source.publisher_key, source.source_type.value,
                                               'none', ChannelStatus.UNAVAILABLE, diagnostic='no_strategy')
                    else:
                        result = strategy.acquire(source, config_path=config_path, data_dir=data_dir, limit=limit)
                    channels.append(result)
                    items = result.items
                    observed[source.id] = items
                    if result.status in (ChannelStatus.SUCCESS, ChannelStatus.EMPTY):
                        failures = [result.diagnostic] if result.diagnostic else []
                        if source.source_type is SourceType.INSTAGRAM and not skip_instagram_evidence and items:
                            try:
                                evidence = self.acquire_evidence(source.id, config_path=config_path,
                                    data_dir=data_dir, limit=limit, observed_items=items)
                                if evidence.failures or evidence.malformed:
                                    failures.append('media_evidence_partial')
                            except Exception:
                                failures.append('media_evidence_failed_caption_available')
                        reports.append(SourceRun(source.id, tuple(i.id for i in items),
                            'partial' if failures else 'success', tuple(failures),
                            result.new, result.changed, result.existing, result.status.value))
                    else:
                        reports.append(SourceRun(source.id, status='failed', channel_status=result.status.value,
                            failures=(f'channel:{result.status.value}',)
                            + ((result.diagnostic,) if result.diagnostic else ())))
                    LOGGER.info('source_collection_finished', extra={'run_id': run_id,
                        'source_id': source.id, 'status': reports[-1].status})
                    save('running')
                for peer in peers:
                    strategy = strategy_for(peer, self.strategies)
                    if strategy is not None:
                        channels.append(strategy.acquire(peer, config_path=config_path, data_dir=data_dir, limit=limit))
                if self.linked is not None:
                    channels.extend(self._linked(selected, peers, observed, data_dir, limit))
                if self.policy_check is not None and peers:
                    try:
                        notices = self.policy_check(peers, state_path=Path(data_dir) / 'state' / 'policy-checks.json',
                                                    now=started)
                    except Exception:
                        LOGGER.warning('policy_recheck_failed', extra={'run_id': run_id})
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
                        status, tuple(errors), prior_source.new, prior_source.changed, prior_source.existing,
                        prior_source.channel_status if collect else ChannelStatus.STORED.value)
                reports = [existing[s.id] for s in selected]
                if not collect:
                    stored_items = {r.source_id: len(r.observed_item_ids) for r in reports}
                    channels = [ChannelResult(s.id, s.publisher_key, s.source_type.value, 'stored',
                                              ChannelStatus.STORED, stored_items.get(s.id, 0)) for s in selected]
                    channels += [strategy.acquire(p, config_path=config_path, data_dir=data_dir, limit=limit)
                                 for p in peers if (strategy := strategy_for(p, self.strategies)) is not None]
                coverage = publisher_coverage(channels)
                represented = {c.publisher_key for c in coverage if c.covered}
                publisher_of = {s.id: s.publisher_key for s in selected}
                # A deliberately unavailable channel (e.g. robots) of a publisher that
                # another channel represented is expected, not a partial run.
                expected = {r.source_id for r in reports if r.channel_status in {c.value for c in DELIBERATE}
                            and publisher_of[r.source_id] in represented}
                failures = tuple(f'{r.source_id}:{error}' for r in reports if r.source_id not in expected
                                 for error in r.failures)
                if review.result.rejected or review.result.diagnostics:
                    failures += ('canonicalization:diagnostics',)
                status = ('failed' if all(r.status == 'failed' for r in reports)
                          else 'partial' if failures else 'success')
                canonical = replace(review.result, events=with_channel_gaps(review.result.events, coverage))
                window = review_window(canonical.events, started, days, review_timezone)
                finished = self.now()
                save('syncing', finished)
                snapshot = self.repository.sync(canonical, window, run_id=run_id,
                    started_at=started, finished_at=finished, days=days, review_timezone=review_timezone,
                    source_count=len(selected), failures=failures, status=status,
                    run_metadata={'selected_source_ids': ids, 'sources': [asdict(r) for r in reports],
                                  'limit': limit, 'mode': mode, 'evidence_mode': evidence_mode,
                                  'channels': [c.record() for c in channels],
                                  'publisher_coverage': [c.record() for c in coverage],
                                  'policy_checks': [n.record() for n in notices]})
                save(status, finished)
                paths, errors = self._export(run_id)
                return RefreshResult(snapshot, tuple(reports), paths, errors, imported,
                                     tuple(channels), coverage, tuple(notices))
            except Exception:
                save('failed_or_unconfirmed', self.now())
                raise

    def _linked(self, selected, peers, observed, data_dir, limit) -> list[ChannelResult]:
        """Depth-one approved linked detail pages named by non-website channels."""
        seeds = [item for s in selected if s.source_type is not SourceType.WEBSITE for item in observed.get(s.id, ())]
        targets = [s for s in (*selected, *peers) if s.source_type is SourceType.WEBSITE]
        results = []
        for target_id, urls in sorted(self.linked.plan(seeds, targets, limit).items()):
            target = next(t for t in targets if t.id == target_id)
            result = self.linked.acquire(target, urls, data_dir=data_dir, limit=limit)
            results.append(result)
            if target.id in observed and result.items:
                current = observed[target.id]
                known = {i.id for i in current}
                observed[target.id] = current + tuple(i for i in result.items if i.id not in known)
        return results

    def _export(self, run_id: str) -> tuple[tuple[Path, ...], tuple[str, ...]]:
        if self.export_reviews is None:
            return (), ()
        try:
            return self.export_reviews(run_id)
        except Exception:
            return (), ('Export failed after persistence; retry offline export for this run ID.',)
