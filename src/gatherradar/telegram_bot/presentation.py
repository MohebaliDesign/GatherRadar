"""Persian texts and inline keyboards. HTML parse mode; every dynamic value escaped."""
from __future__ import annotations

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .services import PlannedFeature, SourceView

# Versioned, short callback data (Telegram allows 64 bytes). Anything else is refused.
PREFIX = 'gr1'
MAIN = f'{PREFIX}:menu'
HELP = f'{PREFIX}:help'
SOURCES = f'{PREFIX}:src:list:'          # + page number
SOURCE = f'{PREFIX}:src:show:'           # + source id
SOON = f'{PREFIX}:soon:'                 # + PlannedFeature value
_CALLBACK = re.compile(
    rf'{PREFIX}:(?:(?P<menu>menu)|(?P<help>help)|src:list:(?P<page>[0-9]{{1,3}})'
    rf'|src:show:(?P<source>[a-z0-9_]{{1,48}})|soon:(?P<soon>[a-z_]{{1,20}}))')
PAGE_SIZE = 8

FEATURES = {
    PlannedFeature.CRAWL_ALL: '🔄 کرال همه منابع',
    PlannedFeature.SELECT_SOURCES: '🎯 انتخاب منابع',
    PlannedFeature.MANAGE_SOURCES: '📋 مدیریت منابع',
    PlannedFeature.EXPORTS: '📊 دریافت خروجی',
    PlannedFeature.RUNS: '🕘 آخرین اجراها',
    PlannedFeature.SETTINGS: '⚙️ تنظیمات',
}
KINDS = {'instagram': 'اینستاگرام', 'website': 'وب‌سایت'}
REASONS = {'robots': 'فایل robots.txt سایت اجازه جمع‌آوری نمی‌دهد'}

NOT_YET = 'این قابلیت در مرحله بعد فعال می‌شود.'
PRIVATE_ONLY = 'این ربات خصوصی است و فقط به مالک خود پاسخ می‌دهد.'
INVALID = 'این گزینه دیگر معتبر نیست. منوی اصلی را دوباره باز کنید.'
ERROR = 'خطایی رخ داد و جزئیات آن در گزارش محلی ثبت شد. دوباره تلاش کنید.'
BOOTSTRAP = ('مالک ربات هنوز تنظیم نشده است.\n'
             'برای دیدن شناسه عددی خود دستور /whoami را بفرستید.')


def e(value: object) -> str:
    """HTML-escape any value that came from configuration or a user."""
    return html.escape(str(value), quote=False)


def parse_callback(data: str | None) -> dict[str, str] | None:
    if not isinstance(data, str) or len(data.encode()) > 64:
        return None
    match = _CALLBACK.fullmatch(data)
    if match is None:
        return None
    return {key: value for key, value in match.groupdict().items() if value is not None}


def main_text() -> str:
    return ('<b>رادار رویدادها</b>\n'
            'از منوی زیر یک گزینه را انتخاب کنید.\n'
            'گزینه‌های «به‌زودی» در مرحله بعد فعال می‌شوند.')


def main_keyboard() -> InlineKeyboardMarkup:
    soon = [InlineKeyboardButton(f'{label} · به‌زودی', callback_data=SOON + feature.value)
            for feature, label in FEATURES.items()]
    rows = [[InlineKeyboardButton('📚 فهرست منابع', callback_data=SOURCES + '0')]]
    rows += [soon[i:i + 2] for i in range(0, len(soon), 2)]
    rows.append([InlineKeyboardButton('❓ راهنما', callback_data=HELP)])
    return InlineKeyboardMarkup(rows)


def help_text() -> str:
    return ('<b>راهنما</b>\n'
            '/menu منوی اصلی\n'
            '/sources فهرست منابع ثبت‌شده (فقط مشاهده)\n'
            '/whoami شناسه عددی تلگرام شما\n'
            '/help همین راهنما\n\n'
            'در این مرحله ربات هیچ جمع‌آوری یا تغییری انجام نمی‌دهد.')


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)]])


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


def sources_keyboard(views: tuple[SourceView, ...], page: int) -> InlineKeyboardMarkup:
    pages = max(1, -(-len(views) // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{"✅" if v.enabled else "⛔️"} {v.name}', callback_data=SOURCE + v.id)]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('◀️ قبلی', callback_data=f'{SOURCES}{page - 1}'))
    if page < pages - 1:
        nav.append(InlineKeyboardButton('بعدی ▶️', callback_data=f'{SOURCES}{page + 1}'))
    if nav:
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
