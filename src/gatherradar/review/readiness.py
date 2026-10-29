"""Explainable data readiness, separate from collection and human decisions.

Optional blank facts are never defects by themselves. Diagnostics describe
known losses/contradictions; this assessment is not a completeness probability.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from ..domain import Event
from ..domain.temporal import DatePrecision


class DataReadiness(StrEnum):
    READY = "ready_for_review"
    ENRICHMENT = "needs_enrichment"
    SCHEDULE = "needs_schedule_review"
    UNAVAILABLE = "source_unavailable"


LABELS = {
    DataReadiness.READY: "آماده بررسی",
    DataReadiness.ENRICHMENT: "نیاز به تکمیل",
    DataReadiness.SCHEDULE: "نیاز به بررسی زمان‌بندی",
    DataReadiness.UNAVAILABLE: "منبع در دسترس نیست",
}
REASON_LABELS = {
    "derived_title": "عنوان توصیفی از شواهد منبع ساخته شده؛ متن شاهد قابل بررسی است",
    "visiting_hours_exception": "بازه نمایشگاه مشخص است؛ تعطیلی و ساعت بازدید را بررسی کنید",
    "source_unavailable": "هیچ کانال منبع در این اجرا در دسترس نبود",
    "missing_title": "عنوان قابل اتکا مشخص نیست",
    "invalid_source_url": "پیوند منبع معتبر نیست",
    "missing_schedule": "تاریخ یا زمان‌بندی مشخص نیست",
    "source_sessions_unreadable": "جلسه‌های صفحه منبع در قالب جدیدی منتشر شده و خوانده نشد؛ تاریخ‌ها را در صفحه منبع بررسی کنید",
    "unresolved_schedule": "زمان‌بندی به بررسی نیاز دارد",
    "inferred_year": "سال تاریخ نیاز به تأیید دارد",
    "temporal_conflict": "شواهد زمان‌بندی ناسازگار است",
    "source_conflict": "شواهد منبع ناسازگار است",
    "extraction_issue": "بخشی از اطلاعات منبع بازیابی نشده است",
    "evidence_incomplete": "شواهد تصویری کامل نیست",
    "session_price_unresolved": "قیمت یا تخفیف جلسه نیاز به بررسی دارد",
    "unreliable_temporal_ocr": "ساعت یا تاریخ خوانده‌شده از تصویر قابل اتکا نیست",
    "ambiguous_description": "انتساب توضیحات منبع به این رویداد روشن نیست",
    "supported_facts_preserved": "اطلاعات لازم برای مرور موجود است",
}
INDICATOR_LABELS = {
    "title_available": "عنوان دارد",
    "date_available": "تاریخ دارد",
    "schedule_unresolved": "زمان‌بندی نامشخص",
    "venue_available": "مکان دارد",
    "description_available": "توضیحات دارد",
    "source_conflict": "تعارض منبع",
    "ocr_evidence_incomplete": "شواهد تصویری ناقص",
}


@dataclass(frozen=True)
class ReadinessAssessment:
    status: DataReadiness
    reasons: tuple[str, ...]
    indicators: tuple[str, ...]

    @property
    def label(self) -> str:
        return LABELS[self.status]

    @property
    def explanation(self) -> str:
        return "؛ ".join(REASON_LABELS[r] for r in self.reasons)


def _valid_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        parts.port
        return bool(parts.scheme in {"http", "https"} and parts.hostname
                    and not parts.username and not parts.password
                    and not any(c.isspace() or ord(c) < 32 for c in value))
    except (ValueError, TypeError):
        return False


def assess_readiness(event: Event, *, source_unavailable: bool = False,
                     evidence_incomplete: bool = False) -> ReadinessAssessment:
    """Classify known data issues; absent optional facts do not lower readiness."""
    indicators, reasons = [], []
    if event.title_review_required:
        reasons.append('derived_title')
    codes = {d.code for d in event.diagnostics}
    if any('visiting_hours_exception' in c for c in codes):
        reasons.append('visiting_hours_exception')
    if any('ocr_clock_needs_review' in c for c in codes):
        reasons.append('unreliable_temporal_ocr')
    temporal = {d.code for d in event.diagnostics
                if d.field in {"temporal", "source_date_text", "source_schedule_text",
                               "occurrences", "source_sessions", "start_date", "start_time", "timezone"}}
    dated = bool(event.start_date and event.date_precision is not DatePrecision.UNKNOWN)
    dated = dated or any(o.start_date is not None for o in event.occurrences)
    schedule_unresolved = (not dated or event.schedule_kind in {"recurring", "conflict"}
                           or any("conflict" in c or "unresolved" in c or
                                  "weekday_mismatch" in c or "invalid" in c or
                                  "unparsed" in c or "ambiguous" in c or
                                  "schema_drift" in c for c in temporal))
    if event.title:
        indicators.append("title_available")
    else:
        reasons.append("missing_title")
    if not _valid_url(event.canonical_source_url):
        reasons.append("invalid_source_url")
    if dated:
        indicators.append("date_available")
    if schedule_unresolved:
        indicators.append("schedule_unresolved")
    if event.venue_name:
        indicators.append("venue_available")
    if event.description_text:
        indicators.append("description_available")
    if any("conflict" in c for c in codes):
        indicators.append("source_conflict")
        reasons.append("temporal_conflict" if any("conflict" in c for c in temporal) else "source_conflict")
    if any("extraction_failed" in c or "extraction_bug" in c for c in codes):
        reasons.append("extraction_issue")
    if any("discount_unresolved" in c or "session_price_unresolved" in c
           or "session_price_unit_unknown" in c for c in codes):
        reasons.append("session_price_unresolved")
    if any("unreliable_temporal_ocr" in c for c in codes):
        reasons.append("unreliable_temporal_ocr")
        schedule_unresolved = True
        if "schedule_unresolved" not in indicators:
            indicators.append("schedule_unresolved")
    if any("ambiguous_caption_description" in c for c in codes):
        reasons.append("ambiguous_description")
    if evidence_incomplete or any("ocr" in c and ("failed" in c or "incomplete" in c) for c in codes):
        indicators.append("ocr_evidence_incomplete")
        reasons.append("evidence_incomplete")
    if any("session_schema_drift" in c or "sessions_schema_drift" in c for c in codes) and not any(
            o.source_session_id for o in event.occurrences):
        # Public session data exists but its shape is unsupported: never guess
        # dates, but say where the dates are instead of only "missing".
        reasons.append("source_sessions_unreadable")
    if schedule_unresolved:
        reasons.append("unresolved_schedule" if event.source_schedule_text or event.source_date_text
                       or event.occurrences else "missing_schedule")
    inferred = event.date_precision is DatePrecision.INFERRED or any(
        o.date_precision is DatePrecision.INFERRED for o in event.occurrences)
    if inferred:
        reasons.append("inferred_year")
    if source_unavailable:
        status = DataReadiness.UNAVAILABLE
        reasons.insert(0, "source_unavailable")
    elif any(r in reasons for r in ("missing_title", "invalid_source_url", "source_conflict",
                                    "extraction_issue", "evidence_incomplete", "session_price_unresolved",
                                    "ambiguous_description")):
        status = DataReadiness.ENRICHMENT
    elif schedule_unresolved or inferred or "temporal_conflict" in reasons:
        status = DataReadiness.SCHEDULE
    else:
        status = DataReadiness.READY
        reasons.append("supported_facts_preserved")
    return ReadinessAssessment(status, tuple(dict.fromkeys(reasons)), tuple(indicators))


def readiness_record(event: Event, *, source_unavailable: bool = False,
                     evidence_incomplete: bool = False) -> dict:
    value = assess_readiness(event, source_unavailable=source_unavailable,
                             evidence_incomplete=evidence_incomplete)
    return {"data_readiness": value.status.value, "readiness_label": value.label,
            "readiness_reasons": list(value.reasons), "readiness_explanation": value.explanation,
            "quality_indicators": list(value.indicators)}


def run_readiness_record(event: Event, metadata: dict) -> dict:
    channels = [c for c in metadata.get("channels", ()) if c.get("source_id") in event.source_ids]
    unavailable = bool(channels) and all(
        c.get("status") in {"unavailable", "policy_blocked", "access_restricted",
                            "temporary_failure", "parse_failure"} for c in channels)
    incomplete = any(f == source + ":media_evidence_partial"
                     for f in metadata.get("source_failures", ())
                     for source in event.source_ids)
    return readiness_record(event, source_unavailable=unavailable, evidence_incomplete=incomplete)
