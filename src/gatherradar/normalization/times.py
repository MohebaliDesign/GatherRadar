"""Strict 24-hour time grammar; no implicit overnight rollover or AM/PM guessing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from .models import Diagnostic, Severity

_CLOCK = r"([0-9]{1,2})(?::([0-9]{2}))?"
_RANGE = re.compile(rf"(?:از\s+)?(?:ساعت\s*)?{_CLOCK}\s*(?:تا|الی|to|–|-)\s*(?:ساعت\s*)?{_CLOCK}")
_SINGLE = re.compile(rf"(?:ساعت\s*)?{_CLOCK}")


@dataclass(frozen=True)
class ParsedTimes:
    start: time | None = None
    end: time | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


def parse_times(text: str) -> ParsedTimes:
    text = text.strip(" ,،؛;.📅🗓⏰🕒")
    text = re.sub(r"^(?:زمان|تاریخ)\s*[:：]\s*", "", text).strip()
    if not text:
        return ParsedTimes()
    match = _RANGE.fullmatch(text) or _SINGLE.fullmatch(text)
    if not match or (match.re is _SINGLE and ":" not in text and "ساعت" not in text):
        return ParsedTimes(diagnostics=(Diagnostic("unparsed_temporal", "source_date_text", "Temporal wording is not a supported single date/time expression."),))
    try:
        start = time(int(match[1]), int(match[2] or 0))
        end = time(int(match[3]), int(match[4] or 0)) if match.re is _RANGE else None
    except ValueError:
        return ParsedTimes(diagnostics=(Diagnostic("invalid_time", "source_date_text", "Hour or minute is outside the 24-hour clock.", Severity.ERROR),))
    if end is not None and end <= start:
        return ParsedTimes(start, end, (Diagnostic("ambiguous_overnight", "source_date_text", "End is not later than start; no overnight day was inferred."),))
    return ParsedTimes(start, end)
