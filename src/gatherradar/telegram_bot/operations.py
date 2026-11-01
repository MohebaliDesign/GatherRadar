"""Local implementation of the bot's application boundary.

Crawls run through the same `RefreshService` wiring as `gatherradar refresh`
(same database, workbook and exports under the data directory). Reads use the
persisted SQLite review projection and the workbook written by the existing XLSX
exporter; nothing here rediscovers, renormalizes or re-exports events.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..review.models import ReviewError
from .jobs import JobManager, JobRecord, JobStore
from .services import SourceCatalog, SourceView

LOGGER = logging.getLogger('gatherradar.telegram')
TEHRAN = ZoneInfo('Asia/Tehran')
MAX_WORKBOOK_BYTES = 45 * 1024 * 1024  # Telegram bots may send documents up to 50 MB


class ScopeError(ValueError):
    """A selection that may not run (unknown, disabled or empty)."""


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: datetime | None
    mode: str                      # refresh | stored_sync | incomplete
    status: str
    source_ids: tuple[str, ...]
    source_status: dict
    discovered: int | None = None  # Event candidates before title admission
    excluded_missing_title: int | None = None
    canonical: int | None = None   # unique canonical Events
    actionable: int | None = None
    schedule_review: int | None = None
    expired: int | None = None
    persisted: bool = True

    @property
    def token(self) -> str:
        return self.run_id[:12]


@dataclass(frozen=True)
class WorkbookCheck:
    ok: bool
    path: Path | None = None
    filename: str | None = None
    sheet: str | None = None
    reason: str | None = None      # safe Persian explanation


def _summary(meta: dict) -> RunSummary:
    started = meta.get('started_at')
    dispositions = meta.get('disposition_counts') or {}
    return RunSummary(
        run_id=meta['run_id'], started_at=datetime.fromisoformat(started) if started else None,
        mode=meta.get('mode', 'refresh'), status=meta.get('status', 'unknown'),
        source_ids=tuple(meta.get('selected_source_ids') or ()),
        source_status={s.get('source_id'): s.get('status') for s in meta.get('sources') or () if isinstance(s, dict)},
        discovered=meta.get('discovered_event_count'), excluded_missing_title=meta.get('excluded_missing_title'),
        canonical=meta.get('canonical_event_count'), actionable=meta.get('event_count'),
        schedule_review=dispositions.get('needs_schedule_review', meta.get('undated')),
        expired=dispositions.get('expired'))


class LocalOperations:
    def __init__(self, catalog: SourceCatalog, *, data_dir: str | Path = 'data',
                 config_path: str | Path = 'config/sources.yaml', limit: int = 5, days: int = 14,
                 refresh_runner: Callable | None = None) -> None:
        self.catalog = catalog
        self.data_dir = Path(data_dir)
        self.config_path = Path(config_path)
        self.limit, self.days = limit, days
        self.database = self.data_dir / 'state' / 'gatherradar.sqlite3'
        self.workbook = self.data_dir / 'review' / 'GatherRadar.xlsx'
        self.exports = self.data_dir / 'exports'
        self.refresh_runner = refresh_runner or self._refresh
        self.jobs = JobManager(JobStore(self.data_dir / 'telegram' / 'jobs.json'), self._run_job)

    # -- sources -----------------------------------------------------------------
    def enabled_sources(self) -> tuple[SourceView, ...]:
        return tuple(v for v in self.catalog.list() if v.enabled)

    def resolve_scope(self, source_ids: tuple[str, ...] | None) -> tuple[str, ...]:
        """None means all enabled. Unknown or disabled IDs are refused, never dropped."""
        enabled = {v.id: v for v in self.enabled_sources()}
        if source_ids is None:
            if not enabled:
                raise ScopeError('no enabled sources')
            return tuple(enabled)
        if not source_ids or any(i not in enabled for i in source_ids):
            raise ScopeError('selection contains an unknown or disabled source')
        return tuple(i for i in enabled if i in set(source_ids))  # registry order

    # -- crawl jobs --------------------------------------------------------------
    def start_crawl(self, source_ids: tuple[str, ...] | None) -> JobRecord:
        scope = self.resolve_scope(source_ids)
        return self.jobs.start(scope, all_enabled=source_ids is None)

    def _run_job(self, record: JobRecord, update: Callable[[JobRecord], None],
                 should_stop: Callable[[], bool]) -> JobRecord:
        from ..orchestration.refresh import RunCancelled
        state = {'record': replace(record, stage='starting')}
        update(state['record'])

        def progress(stage: str, details: dict) -> None:
            current = state['record']
            if stage == 'source_started':
                current = replace(current, stage='collecting', current_source=details.get('source_id'),
                                  done_sources=details.get('index', 1) - 1, total_sources=details.get('total', 0))
            elif stage == 'source_finished':
                statuses = dict(current.source_status, **{details.get('source_id'): details.get('status')})
                current = replace(current, stage='collecting', source_status=statuses,
                                  done_sources=details.get('index', 0), current_source=None)
            else:
                current = replace(current, stage=stage, current_source=None)
            state['record'] = current
            update(current)
        try:
            outcome = self.refresh_runner(record, progress, should_stop)
        except RunCancelled:
            return replace(state['record'], status='cancelled', stage='done', current_source=None,
                           message='اجرا پیش از تحلیل متوقف شد؛ هیچ نتیجه‌ای ثبت نشد.')
        except ReviewError as error:
            return replace(state['record'], status='error', stage='done',
                           message=_safe_review_error(str(error)))
        except Exception as error:
            LOGGER.error('telegram_crawl_failed: %s', type(error).__name__, exc_info=error)
            return replace(state['record'], status='error', stage='done',
                           message='اجرا با خطا متوقف شد؛ جزئیات در گزارش محلی ثبت شد.')
        status, export_failures = outcome
        xlsx_failed = any(e.startswith(('ExcelReviewExporter', 'XLSX')) for e in export_failures)
        return replace(state['record'], status=status, stage='done', current_source=None,
                       export_ok=not xlsx_failed,
                       message='ساخت فایل Excel ناموفق بود؛ داده‌ها ذخیره شده‌اند.' if xlsx_failed else None)

    def _refresh(self, record: JobRecord, progress, should_stop) -> tuple[str, tuple[str, ...]]:
        """Runs in the worker thread with its own SQLite connection."""
        from ..orchestration.refresh import application_refresh_service
        from ..review.workspace import local_workspace
        from ..storage.sqlite_repository import SqliteCanonicalRepository
        with SqliteCanonicalRepository(self.database) as repository:
            workspace = local_workspace(repository, self.workbook, self.exports)
            service = application_refresh_service(repository, workspace)
            result = service.run(() if record.all_enabled else record.scope, all_enabled=record.all_enabled,
                                 config_path=self.config_path, data_dir=self.data_dir, limit=self.limit,
                                 days=self.days, run_id=record.job_id, progress=progress, should_stop=should_stop)
        return result.snapshot.status, tuple(result.export_failures)

    # -- persisted runs (read-only) ------------------------------------------------
    def _repository(self):
        from ..storage.sqlite_repository import SqliteCanonicalRepository
        if not self.database.exists():  # never create a database from a read action
            return None
        return SqliteCanonicalRepository(self.database)

    def recent_runs(self, limit: int = 10) -> tuple[RunSummary, ...]:
        runs = []
        repository = self._repository()
        if repository is not None:
            with repository:
                runs = [_summary(meta) for meta in repository.list_runs()]
        known = {r.run_id for r in runs}
        # Bot jobs that never reached the database (cancelled, interrupted, failed).
        for job in self.jobs.store.read():
            if job.job_id not in known and job.status not in ('running', 'cancelling'):
                runs.append(RunSummary(job.job_id, datetime.fromisoformat(job.created_at), 'incomplete',
                                       job.status, job.scope, dict(job.source_status), persisted=False))
        runs.sort(key=lambda r: r.started_at or datetime.min.replace(tzinfo=TEHRAN), reverse=True)
        return tuple(runs[:limit])

    def find_run(self, token: str) -> RunSummary | None:
        matches = [r for r in self.recent_runs(limit=200) if r.run_id.startswith(token)]
        return matches[0] if len(matches) == 1 else None

    def run_document(self, run_id: str) -> dict | None:
        repository = self._repository()
        if repository is None:
            return None
        with repository:
            try:
                return repository.load(run_id)
            except ReviewError:
                return None

    def latest_exported_run(self) -> RunSummary | None:
        for run in self.recent_runs(limit=50):
            if run.persisted and self.workbook_for(run.run_id).ok:
                return run
        return None

    def _workbook_index(self, path: Path) -> tuple[set, list]:
        """Sheet names and run index, re-read only when the file changes."""
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = getattr(self, '_index_cache', None)
        if cached is None or cached[0] != key:
            cached = (key, _read_index(path))
            self._index_cache = cached
        return cached[1]

    def workbook_for(self, run_id: str) -> WorkbookCheck:
        """The existing workbook, only if its run index holds this run's snapshot."""
        job = self.jobs.store.get(run_id)
        if job is not None and job.export_ok is False:
            return WorkbookCheck(False, reason='ساخت فایل Excel برای این اجرا ناموفق بود.')
        path = self.workbook
        try:
            if not path.is_file():
                return WorkbookCheck(False, reason='فایل Excel هنوز ساخته نشده است.')
            if path.stat().st_size > MAX_WORKBOOK_BYTES:
                return WorkbookCheck(False, reason='فایل Excel برای ارسال در تلگرام بیش از حد بزرگ است.')
            names, rows = self._workbook_index(path)
        except Exception as error:
            LOGGER.warning('telegram_workbook_unreadable: %s', type(error).__name__)
            return WorkbookCheck(False, reason='فایل Excel خوانا نیست؛ خروجی را دوباره بسازید.')
        row = next((r for r in rows if r and r[0] == run_id), None)
        sheet = row[8] if row is not None and len(row) > 8 else None
        if not sheet or sheet not in names:
            return WorkbookCheck(False, reason='فایل Excel فعلی برگه این اجرا را ندارد.')
        run = self.find_run(run_id[:12])
        stamp = run.started_at.astimezone(TEHRAN).strftime('%Y%m%d-%H%M') if run and run.started_at else 'run'
        return WorkbookCheck(True, path, f'GatherRadar-{stamp}-{run_id[:8]}.xlsx', sheet)


def _read_index(path: Path) -> tuple[set, list]:
    from openpyxl import load_workbook
    from ..exports.excel import RUNS
    book = load_workbook(path, read_only=True)
    try:
        names = set(book.sheetnames)
        rows = list(book[RUNS].iter_rows(min_row=2, values_only=True)) if RUNS in names else []
    finally:
        book.close()
    return names, rows


def _safe_review_error(message: str) -> str:
    if 'lock' in message.lower():
        return 'عملیات دیگری روی پایگاه داده در جریان است (مثلاً اجرای خط فرمان). پس از پایان آن دوباره تلاش کنید.'
    return 'اجرا انجام نشد؛ جزئیات در گزارش محلی ثبت شد.'
