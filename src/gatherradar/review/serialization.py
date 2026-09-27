"""Pure review presentation; no spreadsheet client or source mutation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from persiantools.jdatetime import JalaliDate

from ..deduplication.models import CanonicalizationResult, MatchKind
from ..deduplication.keys import stable_id
from ..domain import Event, PlaceCandidate
from ..domain.temporal import DatePrecision
from .schema import DECISIONS

WEEKDAYS = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')
MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
STATUS = {'unknown': 'نامشخص', 'upcoming': 'پیش رو', 'expired': 'پایان یافته',
          'cancelled': 'لغو شده', 'postponed': 'به تعویق افتاده', 'sold_out': 'تکمیل ظرفیت'}
FORMATS = {'in_person': 'حضوری', 'online': 'آنلاین', 'hybrid': 'ترکیبی', 'unknown': 'نامشخص'}
REASONS = {
    'exact_date_match': 'تاریخ یکسان', 'uncertain_date_match': 'تاریخ مشابه با قطعیت ناکافی',
    'uncertain_date_difference': 'اختلاف در تاریخ نامطمئن',
    'distinctive_title_exact': 'عنوان متمایز یکسان', 'distinctive_title_strong': 'عنوان بسیار مشابه',
    'title_similarity_only': 'شباهت عنوان به‌تنهایی کافی نیست', 'city_match': 'شهر یکسان',
    'venue_name_match': 'نام مکان یکسان', 'address_match': 'آدرس یکسان',
    'start_time_match': 'زمان شروع یکسان', 'end_time_match': 'زمان پایان یکسان',
    'uncertain_start_time_difference': 'اختلاف در ساعت شروع نامطمئن',
    'uncertain_end_time_difference': 'اختلاف در ساعت پایان نامطمئن',
    'registration_url_match': 'پیوند ثبت‌نام یکسان', 'different_registration_urls': 'پیوندهای ثبت‌نام متفاوت',
    'same_publisher': 'ناشر مشترک', 'insufficient_occurrence_evidence': 'شواهد برای یکی دانستن رویداد کافی نیست',
    'same_source_page': 'صفحه منبع یکسان',
    'all_member_grouping_blocked': 'همه اعضای گروه با هم سازگار نیستند',
}


def persian(value: object) -> str:
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def jalali(value: date | None) -> str:
    if value is None:
        return ''
    j = JalaliDate(value)
    return f'{persian(j.day)} {MONTHS[j.month - 1]} {persian(j.year)}'


def url(value: str | None) -> str:
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username
                or parsed.password or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ValueError('invalid review URL') from None
    return value


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def iso(value: object) -> str:
    return value.isoformat() if value is not None else ''


def quality(event: Event) -> str:
    if any('conflict' in d.code or 'unresolved_temporal' in d.code for d in event.diagnostics):
        return 'تعارض داده'
    if event.start_date is None or event.date_precision is DatePrecision.UNKNOWN:
        return 'تاریخ نامشخص'
    if event.diagnostics or event.date_precision is DatePrecision.INFERRED:
        return 'نیاز به بررسی'
    if not event.title or not event.event_format or (not event.venue_name and event.event_format != 'online'):
        return 'اطلاعات ناقص'
    return 'کامل'


def price(event: Event) -> str:
    if event.price_text:
        return event.price_text
    if event.price_amount is None:
        return ''
    if event.price_amount == 0:
        return 'رایگان'
    unit = {'TOMAN': 'تومان', 'IRR': 'ریال'}.get(event.currency, event.currency or '')
    return f'{persian(format(event.price_amount, "f"))} {unit}'.strip()


def schedule(event: Event) -> str:
    """Visible source schedule wording, without repeating a fully modelled date.

    Multi-session/recurring wording is always shown. Otherwise the primary
    source date text is shown only when normalized date/time is incomplete,
    inferred or diagnosed; the full machine values stay in portable exports.
    """
    if event.source_schedule_text:
        return event.source_schedule_text
    incomplete = (event.start_date is None
                  or event.date_precision in {DatePrecision.UNKNOWN, DatePrecision.INFERRED}
                  or any(d.field in {'temporal', 'source_date_text'} for d in event.diagnostics))
    return (event.source_date_text or '') if incomplete else ''


def event_row(event: Event, run_id: str, human: tuple[str, str] | None = None) -> list:
    decision, note = human if human is not None else (DECISIONS[0], '')
    links = sorted({url(u) for u in (*event.evidence_urls, event.canonical_source_url) if u})
    visible = [decision, event.title, event.category, STATUS[event.status.value],
        jalali(event.start_date), WEEKDAYS[event.start_date.weekday()] if event.start_date else '',
        persian(event.start_time.strftime('%H:%M')) if event.start_time else '', jalali(event.end_date),
        persian(event.end_time.strftime('%H:%M')) if event.end_time else '', schedule(event),
        event.venue_name, event.area_text, event.city, event.address, event.duration_text, price(event),
        event.availability_text, FORMATS.get(event.event_format, ''), event.description_text,
        event.organizer_name, url(event.registration_url), url(event.canonical_source_url), '\n'.join(links),
        len(event.source_ids) or len(links), quality(event), note]
    technical = [event.event_id, run_id, iso(event.start_date), iso(event.end_date), event.timezone,
        event.date_precision.value, iso(event.starts_at), iso(event.ends_at),
        str(event.price_amount) if event.price_amount is not None else '', event.currency,
        event.source_date_text, event.source_schedule_text, encoded(event.source_ids), encoded(event.publisher_keys),
        encoded(event.candidate_ids), encoded(event.source_item_ids), encoded(links),
        url(event.canonical_source_url), encoded([asdict(d) for d in event.diagnostics]),
        iso(event.first_seen_at), iso(event.last_seen_at), event.duplicate_group_id,
        encoded([asdict(p) for p in event.field_provenance]), event.extraction_confidence]
    return [v if v is not None else '' for v in visible + technical]


def place_row(place: PlaceCandidate, run_id: str, source_id: str) -> list:
    return [v if v is not None else '' for v in [DECISIONS[0], place.title, place.category,
        place.city, place.address, place.opening_hours_text, place.price_text, place.summary,
        url(place.evidence_url), '', place.candidate_id, place.raw_item_id, source_id,
        run_id, url(place.evidence_url)]]


@dataclass(frozen=True)
class ReviewWindow:
    events: tuple[Event, ...]
    filtered: int
    undated: int


def review_window(events: tuple[Event, ...], started_at: datetime, days: int = 14,
                  review_timezone: str = 'Asia/Tehran') -> ReviewWindow:
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('days must be between 1 and 90')
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError('run start must be timezone-aware')
    today = started_at.astimezone(ZoneInfo(review_timezone)).date()
    horizon = today + timedelta(days=days)
    retained, undated = [], 0
    for event in events:
        unresolved = event.start_date is None or event.date_precision is DatePrecision.UNKNOWN
        if unresolved:
            undated += 1
        elif (event.end_date or event.start_date) < today or event.start_date > horizon:
            continue
        retained.append(event)
    retained.sort(key=lambda e: (e.start_date is None or e.date_precision is DatePrecision.UNKNOWN,
        e.start_date or date.max, e.start_time is None, iso(e.start_time), e.title or '', e.event_id))
    return ReviewWindow(tuple(retained), len(events) - len(retained), undated)


def snapshot_title(kind: str, started_at: datetime, review_timezone: str) -> str:
    local = started_at.astimezone(ZoneInfo(review_timezone))
    return f'{kind}_{JalaliDate(local.date()).isoformat()}_{local:%H%M}'


def duplicate_rows(result: CanonicalizationResult, run_id: str) -> list[list]:
    membership = {cid: e for e in result.events for cid in e.candidate_ids}
    rows = {}
    for pair in result.possible_duplicates:
        if pair.kind is not MatchKind.POSSIBLE_DUPLICATE:
            continue
        a, b = (membership.get(cid) for cid in pair.candidate_ids)
        if a is None or b is None or a.event_id == b.event_id:
            continue
        a, b = sorted((a, b), key=lambda e: e.event_id)
        key = stable_id('pair:', (a.event_id, b.event_id))
        # Aggregate candidate-level reasons for the same canonical pair.
        reasons = set(pair.reasons)
        if key in rows:
            reasons.update(rows[key][7].split('\n'))
        rows[key] = [DECISIONS[0], a.title or '', jalali(a.start_date),
            '\n'.join(url(u) for u in a.evidence_urls), b.title or '', jalali(b.start_date),
            '\n'.join(url(u) for u in b.evidence_urls), '\n'.join(sorted(reasons)), '',
            key, a.event_id, b.event_id, run_id, run_id]
    output = []
    for key in sorted(rows):
        row = rows[key]
        codes = row[7].split('\n')
        row[7] = '\n'.join(dict.fromkeys(REASONS.get(code, 'نیاز به بررسی شواهد') for code in codes))
        row.append(encoded(codes))
        output.append(row)
    return output
