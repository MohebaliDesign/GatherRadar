"""Source-neutral date/time composition, reference selection, and timezone validation."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain import RawItem, Source
from ..domain.temporal import DatePrecision
from .dates import parse_dates
from .models import Diagnostic, Severity, TemporalResult
from .text import fold
from .times import parse_times

_RECURRING = re.compile(r"(?<!\w)(?:هر\s*(?:هفته|روز|شب|ماه|شنبه|یکشنبه|دوشنبه|سه شنبه|چهارشنبه|پنجشنبه|جمعه)|روزانه|هفتگی|ساعات بازدید|every|daily|weekly)(?!\w)")


def _local_datetime(day, clock, zone: ZoneInfo) -> datetime | None:
    """Reject DST gaps and folds rather than arbitrarily choosing an offset."""
    naive = datetime.combine(day, clock)
    first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None
    if first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return first


def normalize_temporal(source_text: str | None, raw_item: RawItem, source: Source) -> TemporalResult:
    reference = raw_item.published_at if raw_item.published_at is not None else raw_item.captured_at
    basis = "published_at" if raw_item.published_at is not None else "captured_at"
    context = {"reference_at": reference, "reference_basis": basis}
    try:
        zone = ZoneInfo(source.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return TemporalResult(**context, diagnostics=(Diagnostic("invalid_timezone", "timezone", "Configured IANA timezone is invalid or unavailable.", Severity.ERROR),))
    context["timezone"] = source.timezone
    if not isinstance(reference, datetime) or reference.tzinfo is None or reference.utcoffset() is None:
        return TemporalResult(**context, diagnostics=(Diagnostic("invalid_reference", "reference_at", "Stored reference must be an aware datetime.", Severity.ERROR),))
    if source_text is None or not source_text.strip():
        return TemporalResult(**context, diagnostics=(Diagnostic("missing_date", "source_date_text", "No temporal wording was supplied."),))
    if len(source_text) > 4096:
        return TemporalResult(**context, diagnostics=(Diagnostic("temporal_too_long", "source_date_text", "Temporal wording exceeds parsing limit."),))
    text = fold(source_text)
    recurring = bool(_RECURRING.search(text))
    dates = parse_dates(text, reference.astimezone(zone).date())
    diagnostics = list(dates.diagnostics)
    if dates.blocked:
        return TemporalResult(**context, diagnostics=tuple(diagnostics))
    remainder = dates.remainder.strip()
    if dates.start is not None:
        remainder = re.sub(r"^(?:از\s+)?(?:تاریخ\s*[:：]?\s*)?", "", remainder).strip()
    times = parse_times(remainder)
    diagnostics.extend(times.diagnostics)
    if recurring:
        diagnostics.append(Diagnostic("recurring_schedule", "source_date_text", "Recurring or visiting hours are not an occurrence interval."))
    if dates.end is not None and times.start is not None:
        diagnostics.append(Diagnostic("multi_day_hours", "source_date_text", "Date bounds and hours do not establish a continuous multi-day interval."))
    if dates.start is None:
        diagnostics.append(Diagnostic("missing_date", "source_date_text", "No supported calendar date; time alone is partial."))
    starts_at = ends_at = None
    # Any unconsumed prose, recurrence, invalid clock or reversed time blocks composition.
    # Inferred year is reviewable but does not prevent deterministic composition.
    safe = all(d.code in {"inferred_year", "relative_date"} for d in diagnostics)
    if safe and dates.start is not None and dates.end is None and times.start is not None:
        starts_at = _local_datetime(dates.start, times.start, zone)
        if times.end is not None:
            ends_at = _local_datetime(dates.start, times.end, zone)
        if starts_at is None or (times.end is not None and ends_at is None):
            starts_at = ends_at = None
            diagnostics.append(Diagnostic("ambiguous_local_time", "source_date_text", "Local clock falls in a timezone transition gap or fold.", Severity.ERROR))
    precision = DatePrecision.UNKNOWN
    if dates.start is not None:
        precision = DatePrecision.RANGE if dates.end is not None else DatePrecision.DAY
    if starts_at is not None:
        precision = DatePrecision.EXACT
    if dates.start is not None and dates.end is None and any(d.code == "inferred_year" for d in diagnostics):
        precision = DatePrecision.INFERRED
    return TemporalResult(
        **context, start_date=dates.start, end_date=dates.end, start_time=times.start,
        end_time=times.end, starts_at=starts_at, ends_at=ends_at,
        date_precision=precision, diagnostics=tuple(diagnostics),
    )
