"""Persian local review workspace and narrowly scoped human-state import."""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, fields
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

from ..domain import PlaceCandidate
from ..review.models import CanonicalRepository, ReviewError
from ..review.records import event_from_record
from ..review.schema import (DECISIONS, DUPLICATE_DECISIONS, DUPLICATE_HEADERS,
    EVENT_HEADERS, EVENT_VISIBLE, PLACE_HEADERS, PLACE_VISIBLE, GUIDE, GUIDE_ROWS)
from ..review.serialization import event_row, place_row, snapshot_title, url, jalali, persian
from .excel_design import LINK_COLUMN, apply_design, column_style, link_label, CATEGORIES, RUN_STATUS

# 3: source schedule/area/duration/availability/description/organizer columns.
# Version 2 workbooks differ only in new snapshot columns; they are upgraded on
# the next export without rewriting historical snapshots. Older/newer refuse.
WORKBOOK_VERSION = 3
READABLE_VERSIONS = (2, 3)
XLSX_CELL_LIMIT = 32767
DESCRIPTION = 'توضیحات / معرفی'
TRUNCATED = '\n… [متن کامل در review.json و events.csv]'
RUNS, DUPLICATES = 'تاریخچه اجراها', 'بررسی تکراری‌ها'
TOKEN = 'review_token'
DUPLICATE_HEADERS = DUPLICATE_HEADERS + ('source_urls_a','source_urls_b')
INDEX_HEADERS = ('شناسه اجرا', 'تاریخ اجرا', 'وضعیت', 'رویدادهای نمایش داده', 'مکان‌ها', 'تکراری احتمالی',
                 'بازه (روز)', 'خطاها', 'تب رویدادها', 'تب مکان‌ها', 'زمان اجرا',
                 'تعداد منابع', 'کل رویدادها', 'شروع اجرا (ISO)')
LOCAL_EVENT_VISIBLE = EVENT_VISIBLE


def open_workspace(path: Path) -> Workbook:
    try:
        if path.suffix.lower() != '.xlsx' or path.stat().st_size > 50_000_000:
            raise ValueError
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 200_000_000:
                raise ValueError
        workbook = load_workbook(path, data_only=False, keep_links=False)
        if (any(s.max_row > 100000 or s.max_column > 256 for s in workbook)
                or '_meta' not in workbook or workbook['_meta']['A1'].value != 'schema_version'
                or workbook['_meta']['B1'].value not in READABLE_VERSIONS
                or any(name not in workbook for name in (GUIDE, RUNS, DUPLICATES))
                or tuple(c.value for c in workbook[RUNS][1]) != INDEX_HEADERS
                or tuple(c.value for c in workbook[DUPLICATES][1]) != DUPLICATE_HEADERS + (TOKEN,)):
            workbook.close()
            raise ValueError
        return workbook
    except Exception:
        raise ReviewError('Existing XLSX is unreadable or has an incompatible schema. It was not overwritten; restore it or choose a separate --workbook recovery path.') from None


def literal(cell, value: object) -> None:
    if isinstance(value, str):
        # openpyxl would silently truncate long strings; fail instead of losing facts.
        if len(value) > 32767:
            raise ReviewError('A review cell exceeds the XLSX text limit; use JSON/CSV and inspect the source.')
        cell.value = value
        cell.data_type = 's'
    else:
        cell.value = value


def table(sheet, headers: tuple, rows: list[list], visible: int, decisions: tuple = ()) -> None:
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{max(1, len(rows)+1)}'
    for r, values in enumerate([list(headers), *rows], 1):
        for c, value in enumerate(values, 1):
            cell = sheet.cell(r, c)
            literal(cell, value)
            # Only link columns become hyperlinks; a description that happens to
            # start with a URL keeps its full text.
            if r > 1 and c <= visible and isinstance(value, str) and (
                    column_style(headers[c-1]) is LINK_COLUMN or headers[c-1].startswith('پیوند منبع')):
                try:
                    if value.startswith(('https://', 'http://')):
                        targets = value.splitlines()
                        if not all(url(target) for target in targets):
                            raise ValueError
                        cell.hyperlink = targets[0]
                        label = link_label(targets[0], headers[c-1])
                        literal(cell, label + (f' ({persian(len(targets))} منبع)' if len(targets)>1 else ''))
                except ValueError:
                    pass
    apply_design(sheet, headers, visible)
    if decisions:
        validation = DataValidation(type='list', formula1='"' + ','.join(decisions) + '"', allow_blank=False)
        validation.errorTitle = 'مقدار نامعتبر'
        validation.error = 'یکی از گزینه‌های فهرست را انتخاب کنید.'
        validation.showErrorMessage = True
        validation.errorStyle = 'stop'
        sheet.add_data_validation(validation)
        validation.add(f'A2:A{max(1000, len(rows)+100)}')


def _name(kind: str, run: dict, workbook: Workbook) -> str:
    name = snapshot_title(kind, datetime.fromisoformat(run['started_at']), run['review_timezone']).replace('_',' ')
    if len(name) > 31 or name in workbook:
        suffix = sha256(run['run_id'].encode()).hexdigest()[:7]
        name = name[:23] + '_' + suffix
    if name in workbook:
        raise ReviewError('Snapshot name collision; no historical sheet was overwritten.')
    return name


def _duplicate_row(item: dict, token: str) -> list:
    return [item['review_decision'], item['title_a'], item['jalali_date_a'], '\n'.join(item['source_urls_a']),
            item['title_b'], item['jalali_date_b'], '\n'.join(item['source_urls_b']), item['reason'],
            item['review_notes'], item['pair_key'], item['event_id_a'], item['event_id_b'],
            item['first_seen_run'], item['last_seen_run'], '\n'.join(item['reason_codes']),
            '\n'.join(item['source_urls_a']),'\n'.join(item['source_urls_b']), token]


class ExcelReviewExporter:
    def __init__(self, path: str | Path, repository: CanonicalRepository) -> None:
        self.path, self.repository = Path(path), repository
        if self.path.suffix.lower() != '.xlsx':
            raise ReviewError('Local review requires a .xlsx workbook path.')

    def export(self, document: dict) -> tuple[Path, ...]:
        workbook = open_workspace(self.path) if self.path.exists() else self._new()
        temporary = self.path.with_name(self.path.stem + '.' + uuid4().hex + '.tmp.xlsx')
        try:
            run = document['run']
            run_id = run['run_id']
            index = workbook[RUNS]
            known = [list(row) for row in index.iter_rows(min_row=2, values_only=True)]
            ids = [r[0] for r in known]
            if len(set(ids)) != len(ids):
                raise ReviewError('Duplicate run IDs in XLSX index; restore the index before export.')
            for row in known:
                if any(name and name not in workbook for name in row[8:10]):
                    raise ReviewError('Historical XLSX snapshot is missing; restore it or choose a recovery workbook.')
            if run_id not in ids:
                event_name = _name('رویدادها', run, workbook)
                event_rows = []
                # Evidence first, then public reference URLs stated in the evidence
                # (clickable for the owner; their unseen page content is not claimed).
                all_links = [(lambda seen: seen + [u for u in dict.fromkeys(item.get('reference_urls') or ())
                                                   if u not in seen])(sorted(set(item['evidence_urls'] + [item['canonical_source_url']])))
                             for item in document['events']]
                link_count = max((len(links) for links in all_links), default=0)
                # OOXML allows one hyperlink per cell. Extra supporting-source columns
                # keep every URL clickable without formulas or invented links.
                link_count = link_count if link_count > 1 else 0
                link_headers = tuple(f'پیوند منبع {persian(i+1)}' for i in range(link_count))
                for item, links in zip(document['events'], all_links):
                    token = self.repository.review_token('event', item['event_id'], run_id)
                    row = event_row(event_from_record(item), run_id, (item['review_decision'], item['review_notes']))
                    values = dict(zip(EVENT_HEADERS,row))
                    # Unmapped explicit source category is shown as its exact wording.
                    values['دسته‌بندی'] = (CATEGORIES.get(item['category'],item['category'])
                                           or item.get('source_category_text') or '')
                    if len(values[DESCRIPTION]) > XLSX_CELL_LIMIT:
                        # Hard XLSX limit: visibly marked; SQLite/JSON/CSV keep the full text.
                        values[DESCRIPTION] = values[DESCRIPTION][:XLSX_CELL_LIMIT - len(TRUNCATED)] + TRUNCATED
                    event_rows.append([values[h] for h in LOCAL_EVENT_VISIBLE] +
                        (links + [''] * (link_count-len(links)) if link_count else []) + row[len(EVENT_VISIBLE):] +
                        [item['category'],item['event_format'],item['status'],item['registration_url'],token])
                headers = (LOCAL_EVENT_VISIBLE + link_headers + EVENT_HEADERS[len(EVENT_VISIBLE):]
                           + ('category','event_format','status','registration_url',TOKEN))
                table(workbook.create_sheet(event_name, 3), headers, event_rows, len(LOCAL_EVENT_VISIBLE) + link_count, DECISIONS)
                place_name = ''
                if document['places']:
                    place_name = _name('مکان‌ها', run, workbook)
                    rows = []
                    for item in document['places']:
                        place = PlaceCandidate(**{f.name: item[f.name] for f in fields(PlaceCandidate)})
                        row = place_row(place, run_id, item['source_id'] or '')
                        row[0], row[9] = item['review_decision'], item['review_notes']
                        row[2] = CATEGORIES.get(row[2],row[2])
                        rows.append(row + [self.repository.review_token('place', place.candidate_id, run_id)])
                    table(workbook.create_sheet(place_name, 4), PLACE_HEADERS + (TOKEN,), rows, len(PLACE_VISIBLE), DECISIONS)
                stamp = datetime.fromisoformat(run['started_at'])
                from zoneinfo import ZoneInfo
                local = stamp.astimezone(ZoneInfo(run['review_timezone']))
                known.append([run_id, jalali(local.date()), RUN_STATUS.get(run['status'],run['status']),
                    run['event_count'], run['place_count'], run['duplicate_count'], run['days'],
                    '\n'.join(run['source_failures']), event_name, place_name, persian(local.strftime('%H:%M')),
                    run['source_count'],run['event_count']+run['filtered'],run['started_at']])
            known.sort(key=lambda row: datetime.fromisoformat(row[13]),reverse=True)
            # Permanent navigation/queue are rebuildable; historical snapshots are untouched.
            workbook.remove(index)
            table(workbook.create_sheet(RUNS, 1), INDEX_HEADERS, known, len(INDEX_HEADERS)-1)
            for row in workbook[RUNS].iter_rows(min_row=2):
                for cell in row[8:10]:
                    if cell.value:
                        cell.hyperlink = "#'" + cell.value.replace("'", "''") + "'!A1"
            workbook.remove(workbook[DUPLICATES])
            rows = [_duplicate_row(item, self.repository.review_token('duplicate', item['pair_key'], item['last_seen_run']))
                    for item in self.repository.duplicate_queue()]
            table(workbook.create_sheet(DUPLICATES, 2), DUPLICATE_HEADERS + (TOKEN,), rows, 9, DUPLICATE_DECISIONS)
            meta = workbook['_meta']
            for row, values in enumerate((('schema_version', WORKBOOK_VERSION), ('latest_generated_run', run_id),
                                           ('generated_timestamp', run['finished_at'])), 1):
                for column, value in enumerate(values, 1):
                    literal(meta.cell(row, column), value)
            apply_design(meta, ('key','value'),0)
            # Keep old snapshot content intact; navigation follows chronological runs,
            # even when an older persisted run is explicitly re-exported.
            snapshots = [name for row in known for name in row[8:10] if name]
            newest = [name for name in known[0][8:10] if name] if known else []
            ordered = newest + [RUNS,DUPLICATES] + [name for name in snapshots if name not in newest] + [GUIDE,'_meta']
            ordered += [name for name in workbook.sheetnames if name not in ordered]
            for position,name in enumerate(ordered):
                workbook.move_sheet(name, offset=position-workbook.sheetnames.index(name))
            workbook.active = workbook.sheetnames.index(newest[0] if newest else RUNS)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            workbook.save(temporary)
            with temporary.open('r+b') as handle:
                os.fsync(handle.fileno())
            verified = open_workspace(temporary)
            try:
                if verified.sheetnames != workbook.sheetnames:
                    raise ReviewError('Temporary XLSX verification failed.')
                for sheet in workbook:
                    if list(sheet.values) != list(verified[sheet.title].values):
                        # OOXML represents empty literal strings as empty cells.
                        normalized = lambda rows: [[None if v == '' else v for v in r] for r in rows]
                        if normalized(sheet.values) != normalized(verified[sheet.title].values):
                            raise ReviewError('Temporary XLSX cell verification failed.')
            finally:
                verified.close()
            temporary.replace(self.path)
        except PermissionError:
            raise ReviewError('XLSX replacement was blocked, possibly because the workbook is open. Close it and run export --run latest; the old file and SQLite state are preserved.') from None
        finally:
            workbook.close()
            temporary.unlink(missing_ok=True)
        return (self.path,)

    @staticmethod
    def _new() -> Workbook:
        workbook = Workbook()
        workbook.remove(workbook.active)
        guide = [list(row) for row in GUIDE_ROWS[1:]]
        guide[1] = ['بازخوانی داده محلی', 'python -m gatherradar refresh --all-enabled --stored']
        guide += [['ذخیره تصمیم‌ها', 'پیش از اجرای بعد فایل را ذخیره و ببندید. فقط تصمیم و یادداشت وارد SQLite می‌شود.'],
                  ['مکان‌ها', 'تصمیم مکان فقط به همین اجرا تعلق دارد؛ حذف تکرار مکان پیاده‌سازی نشده است.'],
                  ['پیوندها', 'منبع اصلی و ثبت‌نام کلیک‌پذیرند؛ منابع متعدد در ستون‌های پیوند منبع نیز نمایش داده می‌شوند.'],
                  ['درباره', 'GatherRadar فرصت‌های عمومی منابع منتخب را برای مرور و تصمیم شما گردآوری می‌کند.'],
                  ['آخرین رویدادها', 'اولین تب، جدیدترین تصویر رویدادهاست. تاریخچه اجراها پیوند تصاویر قدیمی را نگه می‌دارد.'],
                  ['اصلاح داده', 'تغییر عنوان، زمان، مکان و سایر واقعیت‌ها فقط در همین تصویر دیده می‌شود؛ به داده اصلی وارد نمی‌شود.'],
                  ['خروجی‌ها', 'CSV و JSON برای جابه‌جایی داده و بسته Gemini برای ساخت دستی شیت در پوشه exports قرار دارند.'],
                  ['قلم‌ها', 'برای بهترین نمایش Vazir و Poppins را نصب کنید؛ قلم‌ها همراه فایل نیستند و جایگزین به برنامه نمایش‌دهنده بستگی دارد.'],
                  ['توضیحات بلند', 'متن کامل در سلول است؛ ارتفاع ردیف محدود است و برای خواندن کامل، سلول را باز کنید. فقط متن بیش از سقف Excel علامت‌گذاری و کامل در JSON/CSV نگه داشته می‌شود.']]
        table(workbook.create_sheet(GUIDE), tuple(GUIDE_ROWS[0]), guide, 2)
        table(workbook.create_sheet(RUNS), INDEX_HEADERS, [], len(INDEX_HEADERS))
        table(workbook.create_sheet(DUPLICATES), DUPLICATE_HEADERS + (TOKEN,), [], 9, DUPLICATE_DECISIONS)
        workbook.create_sheet('_meta').sheet_state = 'hidden'
        return workbook


@dataclass(frozen=True)
class ImportSummary:
    imported: int = 0
    skipped: int = 0
    malformed: int = 0
    conflicts: int = 0


class ExcelReviewImporter:
    def __init__(self, path: str | Path, repository: CanonicalRepository) -> None:
        self.path, self.repository = Path(path), repository

    def import_reviews(self) -> ImportSummary:
        if not self.path.exists():
            return ImportSummary()
        workbook = open_workspace(self.path)
        counts = Counter()
        try:
            run_order = {run['run_id']: index for index, run in enumerate(self.repository.list_runs())}
            candidates = []
            for sheet in workbook:
                if sheet.title in (GUIDE, RUNS, '_meta'):
                    continue
                headers = [cell.value for cell in sheet[1]]
                kind = 'duplicate' if sheet.title == DUPLICATES else 'event' if 'event_id' in headers else 'place' if 'candidate_id' in headers else None
                if kind is None:
                    continue  # Owner-added sheets are never ingested.
                key_header = {'event': 'event_id', 'place': 'candidate_id', 'duplicate': 'pair_key'}[kind]
                run_header = 'last_seen_run' if kind == 'duplicate' else 'run_id'
                decision_header = 'تصمیم' if kind == 'duplicate' else 'تصمیم من'
                needed = (key_header, run_header, decision_header, 'یادداشت من', TOKEN)
                if any(headers.count(name) != 1 for name in needed):
                    raise ReviewError('XLSX review/identity headers are missing or duplicated; restore them before importing.')
                for cells in sheet.iter_rows(min_row=2):
                    if not any(c.value is not None for c in cells):
                        continue
                    values = [cells[headers.index(name)] for name in needed]
                    key, run_id, decision, notes, token = [c.value for c in values]
                    if (any(c.data_type == 'f' for c in values) or not all(isinstance(v, str) for v in (key, run_id, token))
                            or run_id not in run_order):
                        counts['malformed'] += 1
                        continue
                    candidates.append((run_order[run_id], kind, key, run_id, decision, notes if notes is not None else '', token))
            # Only newest snapshot containing each Event is eligible; sorting tabs/rows
            # cannot revive an obsolete decision from historical snapshots.
            newest = {}
            occurrences = Counter((kind, key, run_id) for _, kind, key, run_id, *_ in candidates)
            for row in candidates:
                _, kind, key, run_id, *_ = row
                identity = (kind, key, run_id if kind == 'place' else '')
                if identity not in newest or row[0] > newest[identity][0]:
                    newest[identity] = row
            for row in candidates:
                _, kind, key, run_id, decision, notes, token = row
                identity = (kind, key, run_id if kind == 'place' else '')
                if occurrences[(kind, key, run_id)] != 1:
                    counts['malformed'] += 1
                elif row != newest[identity]:
                    counts['skipped'] += 1
                else:
                    outcome = self.repository.import_review(token, kind, key, run_id, decision, notes)
                    counts['conflicts' if outcome == 'conflict' else outcome] += 1
        finally:
            workbook.close()
        return ImportSummary(**{key: counts[key] for key in ('imported', 'skipped', 'malformed', 'conflicts')})
