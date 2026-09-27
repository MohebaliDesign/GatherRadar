"""Local canonical state. SQL and transactions stay at this repository boundary."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from ..deduplication.models import CanonicalizationResult
from ..review.io import LocalState
from ..review.models import ReviewError, SnapshotResult
from ..review.records import SCHEMA_VERSION as EXPORT_VERSION, dumps, event_record, primitive
from ..review.schema import DECISIONS, DUPLICATE_DECISIONS
from ..review.serialization import ReviewWindow, duplicate_rows
from .sqlite_schema import SCHEMA_VERSION, migrate


class SqliteCanonicalRepository:
    def __init__(self, path: str | Path = 'data/state/gatherradar.sqlite3') -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = LocalState(self.path)
        self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.connection.execute('PRAGMA busy_timeout = 5000')
            migrate(self.connection)
            # Local single-owner files: WAL supports readers during brief writes.
            self.connection.execute('PRAGMA journal_mode = WAL')
            self.connection.execute('PRAGMA synchronous = FULL')
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SqliteCanonicalRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def find_run(self, run_id: str) -> SnapshotResult | None:
        row = self.connection.execute('SELECT metadata FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            return None
        run = json.loads(row[0])
        return SnapshotResult(run_id, '', '', '', run['event_count'], run['place_count'],
                              run['duplicate_count'], run['status'], run['filtered'], run['undated'], True)

    def sync(self, result: CanonicalizationResult, window: ReviewWindow, *, run_id: str,
             started_at: datetime, finished_at: datetime, days: int, review_timezone: str,
             source_count: int, failures: tuple[str, ...] = (), status: str = 'success',
             run_metadata: dict | None = None) -> SnapshotResult:
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id) or status not in {'success', 'partial', 'failed'}
                or type(days) is not int or not 1 <= days <= 90 or type(source_count) is not int or source_count < 0
                or any(t.tzinfo is None or t.utcoffset() is None for t in (started_at, finished_at))
                or finished_at < started_at):
            raise ReviewError('Invalid persistence run context.')
        ZoneInfo(review_timezone)
        started_at = started_at.astimezone(timezone.utc)
        finished_at = finished_at.astimezone(timezone.utc)
        events = {e.event_id: e for e in result.events}
        if len(events) != len(result.events) or any(events.get(e.event_id) != e for e in window.events):
            raise ReviewError('Invalid canonical snapshot membership.')
        pairs = duplicate_rows(result, run_id)
        metadata = dict(run_metadata or {})
        metadata.update(run_id=run_id, started_at=started_at.isoformat(), finished_at=finished_at.isoformat(),
            status=status, days=days, review_timezone=review_timezone, source_count=source_count,
            source_failures=list(failures), event_count=len(window.events), canonical_event_count=len(events),
            place_count=len(result.places), duplicate_count=len(pairs), filtered=window.filtered,
            undated=window.undated, diagnostics=primitive(result.diagnostics))
        with self._transaction():
            prior = self.find_run(run_id)
            if prior:
                return prior
            self.connection.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                (run_id, started_at.isoformat(), finished_at.isoformat(), status, dumps(metadata)))
            visible = {event.event_id: index for index, event in enumerate(window.events)}
            for event in result.events:
                anchor = self.connection.execute('SELECT anchor_raw_item_id,anchor_slot FROM event_identity_map WHERE event_id=?', (event.event_id,)).fetchone()
                if anchor and tuple(anchor) != (event.identity_anchor_raw_item_id, event.identity_anchor_slot):
                    raise ReviewError('Event identity anchor conflict; no mapping was reassigned.')
                payload = dumps(event_record(event))
                self.connection.execute('''INSERT INTO events VALUES (?,?,?) ON CONFLICT(event_id)
                    DO UPDATE SET latest_run=excluded.latest_run,payload=excluded.payload
                    WHERE (SELECT started_at FROM runs WHERE run_id=events.latest_run) <=
                          (SELECT started_at FROM runs WHERE run_id=excluded.latest_run)''', (event.event_id, run_id, payload))
                self.connection.execute('INSERT INTO event_snapshots VALUES (?,?,?,?,?)',
                    (run_id, event.event_id, visible.get(event.event_id, len(visible)), int(event.event_id in visible), payload))
                self.connection.execute('''INSERT INTO event_identity_map VALUES (?,?,?,?,?) ON CONFLICT(event_id)
                    DO UPDATE SET last_run=(SELECT latest_run FROM events WHERE event_id=excluded.event_id)''',
                    (event.event_id, event.identity_anchor_raw_item_id, event.identity_anchor_slot, run_id, run_id))
                self.connection.execute('INSERT OR IGNORE INTO event_review VALUES (?,?,?,?)',
                    (event.event_id, DECISIONS[0], '', finished_at.isoformat()))
            sources = {c.raw_item.id: c.source.id for c in result.contexts}
            for place in result.places:
                payload = dict(primitive(place), source_id=sources.get(place.raw_item_id))
                self.connection.execute('INSERT INTO place_snapshots VALUES (?,?,?)', (run_id, place.candidate_id, dumps(payload)))
                self.connection.execute('INSERT INTO place_review VALUES (?,?,?,?,?)',
                    (run_id, place.candidate_id, DECISIONS[0], '', finished_at.isoformat()))
            for row in pairs:
                payload = dict(zip(('review_decision','title_a','jalali_date_a','source_urls_a','title_b',
                    'jalali_date_b','source_urls_b','reason','review_notes','pair_key','event_id_a','event_id_b',
                    'first_seen_run','last_seen_run','reason_codes'), row))
                for name in ('source_urls_a','source_urls_b'):
                    payload[name] = payload[name].splitlines()
                payload['reason_codes'] = json.loads(payload['reason_codes'])
                self.connection.execute('''INSERT INTO duplicate_review VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(pair_key)
                    DO UPDATE SET last_seen_run=excluded.last_seen_run
                    WHERE (SELECT started_at FROM runs WHERE run_id=duplicate_review.last_seen_run) <=
                          (SELECT started_at FROM runs WHERE run_id=excluded.last_seen_run)''',
                    (row[9], row[10], row[11], DECISIONS[0], '', finished_at.isoformat(), run_id, run_id))
                self.connection.execute('INSERT INTO duplicate_snapshots VALUES (?,?,?)', (run_id, row[9], dumps(payload)))
        return SnapshotResult(run_id, '', '', '', len(window.events), len(result.places), len(pairs),
                              status, window.filtered, window.undated)

    def list_runs(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.connection.execute('SELECT metadata FROM runs ORDER BY started_at, rowid')]

    def load(self, run_id: str = 'latest', *, include_filtered: bool = False) -> dict:
        if run_id == 'latest':
            latest = self.connection.execute('SELECT run_id FROM runs ORDER BY started_at DESC,rowid DESC LIMIT 1').fetchone()
            if latest is None:
                raise ReviewError('No persisted runs; run refresh first (or refresh --stored for local observations).')
            run_id = latest[0]
        row = self.connection.execute('SELECT metadata FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise ReviewError('Requested run was not found.')
        document = dict(schema_version=EXPORT_VERSION, run=json.loads(row[0]))
        tables = (
            ('events', 'event_snapshots', 'event_review', 'event_id', 'AND s.visible=1', 's.ordinal,s.event_id'),
            ('places', 'place_snapshots', 'place_review', 'candidate_id', '', 's.candidate_id'),
            ('possible_duplicates', 'duplicate_snapshots', 'duplicate_review', 'pair_key', '', 's.pair_key'),
        )
        for name, snapshots, reviews, key, where, order in tables:
            if name == 'events' and include_filtered:
                where = ''
            extra = 'AND r.run_id=s.run_id' if name == 'places' else ''
            rows = self.connection.execute(f'''SELECT s.payload,r.decision,r.notes,r.updated_at
                FROM {snapshots} s JOIN {reviews} r ON r.{key}=s.{key} {extra}
                WHERE s.run_id=? {where} ORDER BY {order}''', (run_id,))
            document[name] = [dict(json.loads(r[0]), review_decision=r[1], review_notes=r[2], review_updated_at=r[3]) for r in rows]
        return document

    def duplicate_queue(self) -> list[dict]:
        rows = self.connection.execute('''SELECT s.payload,r.decision,r.notes,r.first_seen_run,r.last_seen_run
            FROM duplicate_review r JOIN duplicate_snapshots s ON s.pair_key=r.pair_key AND s.run_id=r.last_seen_run
            ORDER BY r.pair_key''')
        return [dict(json.loads(r[0]), review_decision=r[1], review_notes=r[2], first_seen_run=r[3], last_seen_run=r[4]) for r in rows]

    def _review(self, kind: str, key: str, run_id: str) -> sqlite3.Row | None:
        if kind == 'event':
            return self.connection.execute('''SELECT r.* FROM event_review r JOIN event_snapshots s
                ON s.event_id=r.event_id WHERE s.run_id=? AND s.event_id=? AND s.visible=1''', (run_id, key)).fetchone()
        if kind == 'place':
            return self.connection.execute('SELECT * FROM place_review WHERE run_id=? AND candidate_id=?', (run_id, key)).fetchone()
        if kind == 'duplicate':
            return self.connection.execute('''SELECT r.* FROM duplicate_review r JOIN duplicate_snapshots s
                ON s.pair_key=r.pair_key WHERE s.run_id=? AND s.pair_key=?''', (run_id, key)).fetchone()
        return None

    def review_token(self, kind: str, key: str, run_id: str) -> str:
        row = self._review(kind, key, run_id)
        if row is None:
            raise ReviewError('Unknown review identity.')
        values = (kind, key, run_id, row['decision'], row['notes'])
        token = sha256(dumps(values).encode('utf-8')).hexdigest()
        self.connection.execute('INSERT OR IGNORE INTO review_exports VALUES (?,?,?,?,?,?)', (token, *values))
        return token

    def import_review(self, token: str, kind: str, key: str, run_id: str, decision: str, notes: str) -> str:
        allowed = DUPLICATE_DECISIONS if kind == 'duplicate' else DECISIONS
        if (not isinstance(decision, str) or decision not in allowed or not isinstance(notes, str)
                or len(notes) > 32767):
            return 'malformed'
        with self._transaction():
            baseline = self.connection.execute('SELECT * FROM review_exports WHERE token=?', (token,)).fetchone()
            current = self._review(kind, key, run_id)
            if (baseline is None or current is None or
                    (baseline['kind'], baseline['identity'], baseline['run_id']) != (kind, key, run_id)):
                return 'malformed'
            incoming, old, now = (decision, notes), (baseline['decision'], baseline['notes']), (current['decision'], current['notes'])
            if incoming == old or incoming == now:
                return 'skipped'
            if now != old:
                return 'conflict'
            stamp = datetime.now(timezone.utc).isoformat()
            if kind == 'event':
                self.connection.execute('UPDATE event_review SET decision=?,notes=?,updated_at=? WHERE event_id=?', (decision, notes, stamp, key))
            elif kind == 'place':
                self.connection.execute('UPDATE place_review SET decision=?,notes=?,updated_at=? WHERE candidate_id=? AND run_id=?', (decision, notes, stamp, key, run_id))
            else:
                self.connection.execute('UPDATE duplicate_review SET decision=?,notes=?,updated_at=? WHERE pair_key=?', (decision, notes, stamp, key))
        return 'imported'

    def status(self) -> dict:
        runs = self.list_runs()
        return dict(database=str(self.path), schema_version=SCHEMA_VERSION, runs=len(runs),
                    latest_run=runs[-1]['run_id'] if runs else None)
