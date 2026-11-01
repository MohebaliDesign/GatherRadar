"""Persian texts and inline keyboards. HTML parse mode; every dynamic value escaped.

Callback data is short, versioned and parsed against an allowlist. It carries
only opaque tokens (a run-ID prefix, a page, an index, a one-time confirmation
nonce); event content is always looked up server-side.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .services import PlannedFeature, SourceView

PREFIX = 'gr1'
MAIN = f'{PREFIX}:menu'
HELP = f'{PREFIX}:help'
SOURCES = f'{PREFIX}:src:list:'          # + page
SOURCE = f'{PREFIX}:src:show:'           # + source id
SOON = f'{PREFIX}:soon:'                 # + PlannedFeature value
CRAWL_ALL = f'{PREFIX}:crawl:all'
SELECT = f'{PREFIX}:sel:'                # + page | t:<id>:<page> | all:<page> | clr:<page> | ok
GO = f'{PREFIX}:go:'                     # + one-time nonce
NO = f'{PREFIX}:no:'                     # + one-time nonce
JOB, JOB_CANCEL = f'{PREFIX}:job', f'{PREFIX}:jobx'
OUTPUTS = f'{PREFIX}:out'
EXCEL = f'{PREFIX}:xl:'                  # + run token
EVENTS = f'{PREFIX}:ev:'                 # + run token:kind:page
EVENT = f'{PREFIX}:ed:'                  # + run token:kind:index
RUNS = f'{PREFIX}:runs:'                 # + page
RUN = f'{PREFIX}:run:'                   # + run token
_ID = r'[a-z0-9_]{1,40}'
_TOKEN = r'[A-Za-z0-9_-]{4,12}'
_CALLBACK = re.compile(
    rf'{PREFIX}:(?:(?P<menu>menu)|(?P<help>help)|src:list:(?P<page>[0-9]{{1,3}})'
    rf'|src:show:(?P<source>{_ID})|soon:(?P<soon>[a-z_]{{1,20}})'
    rf'|(?P<crawl_all>crawl:all)'
    rf'|sel:(?:(?P<sel_page>[0-9]{{1,3}})|t:(?P<sel_toggle>{_ID}):(?P<sel_toggle_page>[0-9]{{1,3}})'
    rf'|all:(?P<sel_all>[0-9]{{1,3}})|clr:(?P<sel_clear>[0-9]{{1,3}})|(?P<sel_ok>ok))'
    rf'|go:(?P<go>[A-Za-z0-9]{{8,16}})|no:(?P<no>[A-Za-z0-9]{{8,16}})'
    rf'|(?P<job_cancel>jobx)|(?P<job>job)|(?P<outputs>out)'
    rf'|xl:(?P<excel>{_TOKEN})|ev:(?P<ev_run>{_TOKEN}):(?P<ev_kind>[ar]):(?P<ev_page>[0-9]{{1,3}})'
    rf'|ed:(?P<ed_run>{_TOKEN}):(?P<ed_kind>[ar]):(?P<ed_index>[0-9]{{1,4}})'
    rf'|runs:(?P<runs>[0-9]{{1,2}})|run:(?P<run>{_TOKEN}))')
PAGE_SIZE = 8
EVENTS_PER_PAGE = 5
RUNS_PER_PAGE = 6
MESSAGE_LIMIT = 3900  # below Telegram's 4,096-character text limit

FEATURES = {
    PlannedFeature.CRAWL_ALL: '🔄 کرال همه منابع',
    PlannedFeature.SELECT_SOURCES: '🎯 انتخاب منابع',
    PlannedFeature.MANAGE_SOURCES: '📋 مدیریت منابع',
    PlannedFeature.EXPORTS: '📊 دریافت خروجی',
    PlannedFeature.RUNS: '🕘 آخرین اجراها',
    PlannedFeature.SETTINGS: '⚙️ تنظیمات',
}
UNFINISHED = (PlannedFeature.MANAGE_SOURCES, PlannedFeature.SETTINGS)
KINDS = {'instagram': 'اینستاگرام', 'website': 'وب‌سایت'}
REASONS = {'robots': 'فایل robots.txt سایت اجازه جمع‌آوری نمی‌دهد'}
STAGES = {'queued': 'در صف', 'starting': 'آماده‌سازی', 'collecting': 'جمع‌آوری از منابع',
          'analyzing': 'تحلیل و استخراج رویدادها', 'persisting': 'ذخیره در پایگاه داده',
          'exporting': 'ساخت خروجی Excel', 'done': 'پایان', 'interrupted': 'متوقف‌شده'}
JOB_STATUS = {'running': 'در حال اجرا', 'cancelling': 'در حال توقف (پس از پایان منبع فعلی)',
              'success': 'موفق', 'partial': 'نیمه‌موفق', 'failed': 'ناموفق', 'cancelled': 'لغو شد',
              'error': 'خطا', 'interrupted': 'قطع‌شده'}
SOURCE_STATUS = {'success': '✅', 'partial': '⚠️', 'failed': '❌'}
MODES = {'refresh': 'کرال زنده', 'stored_sync': 'بازپخش داده ذخیره‌شده', 'incomplete': 'ناتمام'}
CATEGORIES = {'performance': 'اجرا', 'workshop': 'کارگاه', 'exhibition': 'نمایشگاه', 'concert': 'کنسرت',
              'festival': 'جشنواره', 'conference': 'همایش', 'talk': 'نشست', 'meetup': 'دورهمی',
              'screening': 'اکران', 'market': 'بازارچه', 'tour': 'تور'}

NOT_YET = 'این قابلیت در مرحله بعد فعال می‌شود.'
PRIVATE_ONLY = 'این ربات خصوصی است و فقط به مالک خود پاسخ می‌دهد.'
INVALID = 'این گزینه دیگر معتبر نیست. منوی اصلی را دوباره باز کنید.'
ERROR = 'خطایی رخ داد و جزئیات آن در گزارش محلی ثبت شد. دوباره تلاش کنید.'
BUSY = 'یک اجرا در جریان است؛ تا پایان آن اجرای جدید شروع نمی‌شود.'
BOOTSTRAP = ('مالک ربات هنوز تنظیم نشده است.\n'
             'برای دیدن شناسه عددی خود دستور /whoami را بفرستید.')


def e(value: object) -> str:
    """HTML-escape any value that came from configuration, a source or a user."""
    return html.escape(str(value), quote=False)


def parse_callback(data: str | None) -> dict[str, str] | None:
    if not isinstance(data, str) or len(data.encode()) > 64:
        return None
    match = _CALLBACK.fullmatch(data)
    if match is None:
        return None
    return {key: value for key, value in match.groupdict().items() if value is not None}


def clip(text: str, limit: int) -> str:
    text = ' '.join(str(text).split()) if '\n' not in str(text) else str(text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def fit(text: str) -> str:
    """Keep a message under Telegram's limit without breaking an HTML tag."""
    if len(text) <= MESSAGE_LIMIT:
        return text
    cut = text[:MESSAGE_LIMIT]
    cut = cut[:cut.rfind('\n')] if '\n' in cut else cut
    return cut + '\n…'


def persian(value: object) -> str:
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def jalali(value: str | date | None) -> str:
    if not value:
        return ''
    from ..review.serialization import jalali as to_jalali
    return to_jalali(date.fromisoformat(value) if isinstance(value, str) else value)


def clock(value: str | None) -> str:
    return persian(time.fromisoformat(value).strftime('%H:%M')) if value else ''


def when(value: datetime | None) -> str:
    if value is None:
        return 'نامشخص'
    from zoneinfo import ZoneInfo
    local = value.astimezone(ZoneInfo('Asia/Tehran'))
    return f'{jalali(local.date())}، {persian(local.strftime("%H:%M"))}'


# -- main menu and help --------------------------------------------------------
def main_text() -> str:
    return ('<b>رادار رویدادها</b>\n'
            'از منوی زیر یک گزینه را انتخاب کنید.')


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(FEATURES[PlannedFeature.CRAWL_ALL], callback_data=CRAWL_ALL),
         InlineKeyboardButton(FEATURES[PlannedFeature.SELECT_SOURCES], callback_data=SELECT + '0')],
        [InlineKeyboardButton(FEATURES[PlannedFeature.EXPORTS], callback_data=OUTPUTS),
         InlineKeyboardButton(FEATURES[PlannedFeature.RUNS], callback_data=RUNS + '0')],
        [InlineKeyboardButton('📚 فهرست منابع', callback_data=SOURCES + '0'),
         InlineKeyboardButton('⏳ وضعیت اجرا', callback_data=JOB)],
        [InlineKeyboardButton(f'{FEATURES[f]} · به‌زودی', callback_data=SOON + f.value) for f in UNFINISHED],
        [InlineKeyboardButton('❓ راهنما', callback_data=HELP)],
    ])


def help_text() -> str:
    return ('<b>راهنما</b>\n'
            '/menu منوی اصلی\n'
            '/sources فهرست منابع ثبت‌شده (فقط مشاهده)\n'
            '/whoami شناسه عددی تلگرام شما\n'
            '/help همین راهنما\n\n'
            'کرال فقط پس از تأیید شما شروع می‌شود و هر بار فقط یک اجرا انجام می‌شود. '
            'منابع غیرفعال هرگز اجرا نمی‌شوند.')


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)]])


# -- source list (Phase 1, read-only) -----------------------------------------
def _state(view: SourceView) -> str:
    if view.enabled:
        return 'فعال'
    reason = REASONS.get(view.disabled_reason or '', view.disabled_reason)
    return 'غیرفعال' + (f' ({e(reason)})' if reason else '')


def sources_text(views: tuple[SourceView, ...]) -> str:
    lines = ['<b>منابع ثبت‌شده</b>', f'فعال: {sum(v.enabled for v in views)} از {len(views)}']
    for kind in ('instagram', 'website'):
        group = [v for v in views if v.kind == kind]
        if not group:
            continue
        lines += ['', f'<b>{KINDS[kind]}</b>']
        lines += [f'{"✅" if v.enabled else "⛔️"} {e(v.name)} — {_state(v)}' for v in group]
    lines += ['', 'برای جزئیات، یک منبع را انتخاب کنید. این فهرست فقط برای مشاهده است.']
    return '\n'.join(lines)


def _pages(count: int, size: int) -> int:
    return max(1, -(-count // size))


def _nav(prefix: str, page: int, pages: int, suffix: str = '') -> list[InlineKeyboardButton]:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('◀️ قبلی', callback_data=f'{prefix}{page - 1}{suffix}'))
    if page < pages - 1:
        nav.append(InlineKeyboardButton('بعدی ▶️', callback_data=f'{prefix}{page + 1}{suffix}'))
    return nav


def sources_keyboard(views: tuple[SourceView, ...], page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{"✅" if v.enabled else "⛔️"} {v.name}', callback_data=SOURCE + v.id)]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    if nav := _nav(SOURCES, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def source_text(view: SourceView) -> str:
    return '\n'.join([
        f'<b>{e(view.name)}</b>',
        f'نوع: {KINDS.get(view.kind, e(view.kind))}',
        f'وضعیت: {_state(view)}',
        f'شناسه: <code>{e(view.id)}</code>',
        f'نشانی: {e(view.public_url)}',
        '',
        'تغییر وضعیت منابع در مرحله بعد اضافه می‌شود.',
    ])


def source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('↩️ فهرست منابع', callback_data=SOURCES + '0')],
        [InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)],
    ])


def whoami_text(user_id: int, bootstrap: bool) -> str:
    text = f'شناسه عددی تلگرام شما: <code>{int(user_id)}</code>'
    if bootstrap:
        text += ('\n\nاین عدد را روی رایانه خودتان در متغیر GATHERRADAR_TELEGRAM_OWNER_ID '
                 'قرار دهید و ربات را دوباره اجرا کنید.')
    return text


# -- crawl configuration and source selection ----------------------------------
def crawl_confirm_text(views: tuple[SourceView, ...], all_enabled: bool, limit: int, days: int) -> str:
    names = '، '.join(e(v.name) for v in views)
    scope = f'همه منابع فعال ({persian(len(views))} منبع)' if all_enabled else f'{persian(len(views))} منبع انتخابی'
    return fit('\n'.join([
        '<b>تأیید کرال</b>',
        f'دامنه: {scope}',
        f'منابع: {names}',
        f'تعداد مطالب اخیر هر منبع: {persian(limit)}',
        f'افق رویدادها: {persian(days)} روز آینده',
        'خروجی: فایل Excel فارسی، فهرست متنی رویدادها، و خروجی‌های CSV/JSON محلی',
        '',
        'منابع غیرفعال (مانند وب‌سایت داوات) اجرا نمی‌شوند. کرال ممکن است چند دقیقه طول بکشد '
        'و برای اینستاگرام مرورگر کروم روی رایانه باز می‌شود.',
    ]))


def confirm_keyboard(nonce: str, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ شروع کرال', callback_data=GO + nonce),
         InlineKeyboardButton('✖️ انصراف', callback_data=NO + nonce)],
        [InlineKeyboardButton('↩️ بازگشت', callback_data=back)],
    ])


def selection_text(views: tuple[SourceView, ...], selected: set[str]) -> str:
    chosen = [v for v in views if v.id in selected]
    lines = ['<b>انتخاب منابع</b>', 'منابع موردنظر را علامت بزنید و سپس «تأیید انتخاب» را بزنید.',
             f'انتخاب‌شده: {persian(len(chosen))} از {persian(len(views))}']
    if chosen:
        lines.append('، '.join(e(v.name) for v in chosen))
    return fit('\n'.join(lines))


def selection_keyboard(views: tuple[SourceView, ...], selected: set[str], page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{"☑️" if v.id in selected else "⬜️"} {v.name} · {KINDS[v.kind]}',
                                  callback_data=f'{SELECT}t:{v.id}:{page}')]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    if nav := _nav(SELECT, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('همه فعال‌ها', callback_data=f'{SELECT}all:{page}'),
                 InlineKeyboardButton('پاک کردن انتخاب', callback_data=f'{SELECT}clr:{page}')])
    rows.append([InlineKeyboardButton('✅ تأیید انتخاب', callback_data=SELECT + 'ok'),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


# -- job progress and completion -----------------------------------------------
def job_text(job, names: dict[str, str]) -> str:
    lines = [f'<b>اجرای کرال</b> · {JOB_STATUS.get(job.status, e(job.status))}',
             f'مرحله: {STAGES.get(job.stage, e(job.stage))}']
    if job.total_sources:
        lines.append(f'منابع انجام‌شده: {persian(job.done_sources)} از {persian(job.total_sources)}')
    if job.current_source:
        lines.append(f'منبع فعلی: {e(names.get(job.current_source, job.current_source))}')
    for source_id, status in job.source_status.items():
        lines.append(f'{SOURCE_STATUS.get(status, "•")} {e(names.get(source_id, source_id))}')
    if job.message:
        lines += ['', e(job.message)]
    return fit('\n'.join(lines))


def job_keyboard(job) -> InlineKeyboardMarkup:
    rows = []
    if job.status == 'running':
        rows.append([InlineKeyboardButton('⏹ توقف پس از منبع فعلی', callback_data=JOB_CANCEL)])
    rows.append([InlineKeyboardButton('🔄 به‌روزرسانی وضعیت', callback_data=JOB),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def run_summary_text(run, names: dict[str, str], export_ok: bool | None, title: str = 'نتیجه اجرا') -> str:
    statuses = {'success': [], 'partial': [], 'failed': []}
    for source_id in run.source_ids:
        statuses.setdefault(run.source_status.get(source_id, 'failed'), []).append(names.get(source_id, source_id))
    lines = [f'<b>{title}</b> · {JOB_STATUS.get(run.status, e(run.status))}',
             f'زمان: {when(run.started_at)} · {MODES.get(run.mode, e(run.mode))}',
             f'منابع: {persian(len(run.source_ids))}']
    for key, label in (('success', '✅ موفق'), ('partial', '⚠️ نیمه‌موفق'), ('failed', '❌ ناموفق')):
        if statuses.get(key):
            lines.append(f'{label}: ' + '، '.join(e(n) for n in statuses[key]))
    if run.persisted:
        lines += ['',
                  f'نامزدهای رویداد کشف‌شده: {persian(run.discovered or 0)}',
                  f'حذف‌شده به دلیل نبود عنوان: {persian(run.excluded_missing_title or 0)}',
                  f'رویدادهای یکتا (پس از ادغام تکراری‌ها): {persian(run.canonical or 0)}',
                  f'• پیش‌رو / در جریان: {persian(run.actionable or 0)}',
                  f'• نیازمند بررسی زمان‌بندی: {persian(run.schedule_review or 0)}',
                  f'• گذشته: {persian(run.expired or 0)}']
    else:
        lines += ['', 'این اجرا به ثبت نتیجه نرسید.']
    if export_ok is True:
        lines.append('خروجی Excel: آماده')
    elif export_ok is False:
        lines.append('خروجی Excel: ناموفق (داده‌ها در پایگاه داده ذخیره شده‌اند)')
    return fit('\n'.join(lines))


def outputs_keyboard(token: str | None, excel: bool) -> InlineKeyboardMarkup:
    rows = []
    if token and excel:
        rows.append([InlineKeyboardButton('📥 دریافت Excel', callback_data=EXCEL + token)])
    if token:
        rows.append([InlineKeyboardButton('📋 نمایش رویدادها', callback_data=f'{EVENTS}{token}:a:0'),
                     InlineKeyboardButton('🗓 بررسی زمان‌بندی', callback_data=f'{EVENTS}{token}:r:0')])
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def excel_caption(run, sheet: str, names: dict[str, str]) -> str:
    scope = '، '.join(names.get(i, i) for i in run.source_ids)
    return clip(f'GatherRadar · {when(run.started_at)}\nدامنه: {scope}\n'
                f'رویدادهای پیش‌رو: {persian(run.actionable or 0)} · بررسی زمان‌بندی: '
                f'{persian(run.schedule_review or 0)}\nبرگه این اجرا: {sheet}', 1000)


# -- run history ---------------------------------------------------------------
def runs_text(runs: tuple, page: int) -> str:
    if not runs:
        return '<b>آخرین اجراها</b>\nهنوز اجرایی ثبت نشده است.'
    return '<b>آخرین اجراها</b>\nبرای جزئیات و خروجی، یک اجرا را انتخاب کنید.'


def runs_keyboard(runs: tuple, page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(runs), RUNS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    rows = []
    for run in runs[page * RUNS_PER_PAGE:(page + 1) * RUNS_PER_PAGE]:
        label = (f'{when(run.started_at)} · {JOB_STATUS.get(run.status, run.status)} · '
                 f'{MODES.get(run.mode, run.mode)}')
        if run.persisted:
            label += f' · {persian(run.actionable or 0)} رویداد'
        rows.append([InlineKeyboardButton(label, callback_data=RUN + run.token)])
    if nav := _nav(RUNS, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


# -- event browsing ------------------------------------------------------------
def _occurrence(record: dict) -> tuple[str, str]:
    """(date text, time text) from persisted values only; nothing is inferred."""
    if record.get('next_session_date'):
        return jalali(record['next_session_date']), clock(record.get('next_session_start_time'))
    if record.get('start_date') and record.get('end_date') and record['end_date'] != record['start_date']:
        return f'{jalali(record["start_date"])} تا {jalali(record["end_date"])}', clock(record.get('start_time'))
    if record.get('start_date'):
        return jalali(record['start_date']), clock(record.get('start_time'))
    occurrences = record.get('occurrences') or []
    if occurrences:
        first = min(occurrences, key=lambda o: (o.get('start_date') or '', o.get('start_time') or ''))
        return jalali(first.get('start_date')), clock(first.get('start_time'))
    return '', ''


def _place(record: dict) -> str:
    parts = [record.get('venue_name'), record.get('area_text'), record.get('city')]
    return '، '.join(e(p) for p in dict.fromkeys(p for p in parts if p))


def _first_line(text: str | None, limit: int) -> str:
    line = next((l.strip() for l in (text or '').splitlines() if l.strip()), '')
    return e(clip(line, limit)) if line else ''


def events_text(records: list[dict], kind: str, page: int, run) -> str:
    title = 'رویدادهای پیش‌رو و در جریان' if kind == 'a' else 'نیازمند بررسی زمان‌بندی'
    pages = _pages(len(records), EVENTS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    lines = [f'<b>{title}</b> · اجرای {when(run.started_at)}',
             f'تعداد: {persian(len(records))} · صفحه {persian(page + 1)} از {persian(pages)}']
    if not records:
        lines += ['', 'در این اجرا موردی در این بخش نیست.']
        return '\n'.join(lines)
    last_day = None
    for number, record in enumerate(records[page * EVENTS_PER_PAGE:(page + 1) * EVENTS_PER_PAGE],
                                    page * EVENTS_PER_PAGE + 1):
        day, hour = _occurrence(record)
        if kind == 'a' and day != last_day:
            lines += ['', f'— {day or "تاریخ نامشخص"} —']
            last_day = day
        elif kind == 'r':
            lines.append('')
        lines.append(f'<b>{persian(number)}. {e(clip(record.get("title") or "بدون عنوان", 90))}</b>')
        detail = []
        if kind == 'a':
            if hour:
                detail.append(f'🕒 {hour}')
        else:
            detail.append('🗓 ' + (e(clip(record.get('source_date_text') or '', 80)) or 'تاریخ اعلام نشده'))
        if place := _place(record):
            detail.append(f'📍 {place}')
        if detail:
            lines.append(' · '.join(detail))
        if summary := _first_line(record.get('description_text'), 110):
            lines.append(summary)
    return fit('\n'.join(lines))


def events_keyboard(records: list[dict], kind: str, page: int, token: str) -> InlineKeyboardMarkup:
    pages = _pages(len(records), EVENTS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    start = page * EVENTS_PER_PAGE
    numbers = [InlineKeyboardButton(f'مشاهده جزئیات {persian(i + 1)}', callback_data=f'{EVENT}{token}:{kind}:{i}')
               for i in range(start, min(start + EVENTS_PER_PAGE, len(records)))]
    rows = [numbers[i:i + 2] for i in range(0, len(numbers), 2)]
    if nav := _nav(f'{EVENTS}{token}:{kind}:', page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ خروجی‌ها', callback_data=RUN + token),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def event_text(record: dict, kind: str, index: int, total: int) -> str:
    day, hour = _occurrence(record)
    lines = [f'<b>{e(record.get("title") or "بدون عنوان")}</b>',
             f'مورد {persian(index + 1)} از {persian(total)}']
    category = CATEGORIES.get(record.get('category') or '') or record.get('source_category_text')
    if category:
        lines.append(f'نوع: {e(category)}')
    if kind == 'a':
        if record.get('next_session_date'):
            lines.append(f'جلسه بعدی: {day}' + (f'، ساعت {hour}' if hour else ''))
            if record.get('remaining_session_count'):
                lines.append(f'جلسه‌های باقی‌مانده در افق: {persian(record["remaining_session_count"])}')
        elif day:
            lines.append(f'تاریخ: {day}' + (f'، ساعت {hour}' if hour else ''))
    if record.get('source_date_text'):
        lines.append(f'زمان اعلام‌شده در منبع: {e(clip(record["source_date_text"], 200))}')
    if place := _place(record):
        lines.append(f'مکان: {place}')
    if record.get('address'):
        lines.append(f'آدرس: {e(clip(record["address"], 200))}')
    if record.get('price_text'):
        lines.append(f'هزینه: {e(clip(record["price_text"], 120))}')
    if record.get('availability_text'):
        lines.append(f'ظرفیت: {e(clip(record["availability_text"], 120))}')
    if record.get('readiness_explanation') and record.get('data_readiness') != 'ready_for_review':
        lines.append(f'نکته بررسی: {e(clip(record["readiness_explanation"], 300))}')
    if description := record.get('description_text'):
        lines += ['', e(clip(description, 900))]
    return fit('\n'.join(lines))


def event_keyboard(record: dict, kind: str, index: int, total: int, token: str) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton('◀️ قبلی', callback_data=f'{EVENT}{token}:{kind}:{index - 1}'))
    if index < total - 1:
        nav.append(InlineKeyboardButton('بعدی ▶️', callback_data=f'{EVENT}{token}:{kind}:{index + 1}'))
    if nav:
        rows.append(nav)
    url = record.get('canonical_source_url') or ''
    if url.startswith(('https://', 'http://')):
        rows.append([InlineKeyboardButton('🔗 مشاهده منبع', url=url)])
    page = index // EVENTS_PER_PAGE
    rows.append([InlineKeyboardButton('✖️ بستن جزئیات', callback_data=f'{EVENTS}{token}:{kind}:{page}'),
                 InlineKeyboardButton('↩️ بازگشت به فهرست', callback_data=f'{EVENTS}{token}:{kind}:0')])
    return InlineKeyboardMarkup(rows)
