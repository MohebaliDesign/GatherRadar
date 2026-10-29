"""Read the observed public Jabama React Router session envelope as data only.

This is deliberately not a JavaScript interpreter or a general Turbo Stream
decoder. Only indexed objects/lists and scalar fields on routes/events.$id are
read. Unrelated loader state, profiles, reviews, tokens and recommendations never
become observations. New envelopes or session shapes produce diagnostics.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlsplit

from ...domain.website import SourceSession
from .html import Node

_ENQUEUE = 'window.__reactRouterContext.streamController.enqueue'
_MAX_PAYLOAD = 1_000_000
_MAX_TABLE = 20_000
_MAX_SESSIONS = 200
_NULL = -5  # The null sentinel observed in the saved public envelope.
_FIELDS = (
    'id', 'eventId', 'startIso', 'durationHours', 'pricePerPerson', 'unitPrice',
    'remainingSeats', 'enabled',
)
_SESSION_KEYS = frozenset((*_FIELDS, 'capacityLimit', 'bookedCount', 'inventoryMode',
                           'layoutId', 'timeslots', 'hostDiscountPct', 'platformDiscountPct'))


@dataclass(frozen=True, slots=True)
class SessionResult:
    sessions: tuple[SourceSession, ...] = ()
    diagnostics: tuple[str, ...] = ()
    present: bool = False


class _SchemaError(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _SchemaError('duplicate JSON key')
        result[key] = value
    return result


def _json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_object_pairs, parse_float=Decimal,
                      parse_constant=lambda _: (_ for _ in ()).throw(_SchemaError('non-finite JSON')))


class _Table:
    """Resolve references only along explicitly requested field paths."""

    def __init__(self, values: object) -> None:
        if not isinstance(values, list) or not 1 <= len(values) <= _MAX_TABLE:
            raise _SchemaError('invalid reference table')
        self.values = values

    def value(self, reference: object) -> object:
        if type(reference) is not int:
            raise _SchemaError('invalid reference')
        if reference == _NULL:
            return None
        if not 0 <= reference < len(self.values):
            raise _SchemaError('unsupported reference')
        return self.values[reference]

    def object(self, reference: object) -> dict[str, object]:
        raw = self.value(reference)
        if not isinstance(raw, dict) or len(raw) > 200:
            raise _SchemaError('expected indexed object')
        result: dict[str, object] = {}
        for encoded_key, value_ref in raw.items():
            if not re.fullmatch(r'_[0-9]+', encoded_key):
                raise _SchemaError('unsupported object encoding')
            key = self.value(int(encoded_key[1:]))
            if not isinstance(key, str) or len(key) > 200 or key in result:
                raise _SchemaError('invalid indexed object key')
            result[key] = value_ref
        return result

    def scalar(self, obj: dict[str, object], key: str, *, required: bool = False) -> object:
        if key not in obj:
            if required:
                raise _SchemaError('missing required field')
            return None
        value = self.value(obj[key])
        if isinstance(value, (dict, list)):
            raise _SchemaError('expected scalar')
        if isinstance(value, str) and len(value) > 200:
            raise _SchemaError('oversized scalar')
        return value


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    if type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
        raise _SchemaError('invalid numeric session field')
    # Fixed notation preserves exact JSON numeric meaning without exponent text.
    return format(Decimal(str(value)), 'f')


def _session(table: _Table, reference: object, event_id: str, index: int) -> SourceSession:
    obj = table.object(reference)
    # Extra session properties can change booking semantics, unlike unrelated
    # event fields. Refuse until their meaning is inspected and fixture-backed.
    if set(obj) - _SESSION_KEYS:
        raise _SchemaError('new session properties')
    values = {key: table.scalar(obj, key, required=key in ('id', 'eventId', 'startIso'))
              for key in _FIELDS}
    if values['eventId'] != event_id:
        raise _SchemaError('session belongs to a different event')
    if 'timeslots' not in obj or table.value(obj['timeslots']) != []:
        raise _SchemaError('unsupported session timeslots')
    # A session discount changes the meaning of its base price. Retain the
    # schedule but omit neither ambiguity nor the price silently.
    for key in ('hostDiscountPct', 'platformDiscountPct'):
        discount = table.scalar(obj, key)
        if discount is not None and (type(discount) not in (int, Decimal)
                                     or not Decimal(discount).is_finite() or not 0 <= discount <= 100):
            raise _SchemaError('invalid session discount')
    return SourceSession(
        source_session_id=values['id'], source_event_id=values['eventId'],
        start_iso=values['startIso'],
        source_locator=f'react-router:loaderData/routes/events.$id/sessions/{index}',
        duration_hours=_decimal(values['durationHours']),
        price_per_person=_decimal(values['pricePerPerson']), unit_price=_decimal(values['unitPrice']),
        host_discount_pct=_decimal(table.scalar(obj, 'hostDiscountPct')),
        platform_discount_pct=_decimal(table.scalar(obj, 'platformDiscountPct')),
        remaining_seats=values['remainingSeats'], enabled=values['enabled'],
    )


def extract_sessions(root: Node, page_url: str) -> SessionResult:
    """Return supported detail sessions, never a firstSession fallback."""
    parts = urlsplit(page_url)
    path = re.fullmatch(r'/events/([A-Za-z0-9_-]{1,100})/?', parts.path)
    if not path:
        return SessionResult(diagnostics=('embedded_sessions_unsupported_path',))
    scripts = [''.join(part for part in node.children if isinstance(part, str)).strip()
               for node in root.select('script') if not node.attrs.get('src')]
    payloads = [script for script in scripts if _ENQUEUE in script]
    if not payloads:
        return SessionResult(diagnostics=('embedded_sessions_absent',))
    if len(payloads) != 1 or len(payloads[0]) > _MAX_PAYLOAD:
        return SessionResult(diagnostics=('embedded_sessions_schema_drift',), present=True)
    # JSON string argument only. No eval, execution, fetching imports, or attempt
    # to repair malformed JavaScript. Trailing program text is rejected.
    match = re.fullmatch(re.escape(_ENQUEUE) + r'\(\s*("(?:[^"\\]|\\.)*")\s*\);?', payloads[0], re.S)
    if not match:
        return SessionResult(diagnostics=('embedded_sessions_schema_drift',), present=True)
    try:
        serialized = _json(match[1])
        if not isinstance(serialized, str) or len(serialized) > _MAX_PAYLOAD:
            raise _SchemaError('invalid serialized table')
        table = _Table(_json(serialized))
        envelope = table.object(0)
        loaders = table.object(envelope['loaderData'])
        route = table.object(loaders['routes/events.$id'])
        event = table.object(route['event'])
        event_id = table.scalar(event, 'id', required=True)
        if event_id != path[1]:
            raise _SchemaError('page event identity mismatch')
        if 'sessions' not in route:
            raise _SchemaError('missing sessions')
        refs = table.value(route['sessions'])
        if not isinstance(refs, list) or len(refs) > _MAX_SESSIONS:
            raise _SchemaError('invalid sessions')
        if not refs:
            return SessionResult(diagnostics=('embedded_sessions_empty',), present=True)
        sessions: dict[str, SourceSession] = {}
        conflicts: set[str] = set()
        diagnostics: list[str] = []
        for index, reference in enumerate(refs):
            try:
                session = _session(table, reference, event_id, index)
                if session.source_session_id in sessions:
                    before, after = sessions[session.source_session_id].to_dict(), session.to_dict()
                    before.pop('source_locator')
                    after.pop('source_locator')
                    if before != after:
                        conflicts.add(session.source_session_id)
                        diagnostics.append('embedded_session_identity_conflict')
                    continue
                sessions[session.source_session_id] = session
                if session.price_per_person is not None or session.unit_price is not None:
                    diagnostics.append('embedded_session_price_unit_unknown')
                obj = table.object(reference)
                if any(table.scalar(obj, key) not in (None, 0)
                       for key in ('hostDiscountPct', 'platformDiscountPct')):
                    diagnostics.append('embedded_session_discount_unresolved')
            except (ValueError, KeyError, TypeError, OverflowError):
                diagnostics.append('embedded_session_schema_drift')
        return SessionResult(tuple(value for key, value in sessions.items() if key not in conflicts),
                             tuple(dict.fromkeys(diagnostics)), True)
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return SessionResult(diagnostics=('embedded_sessions_schema_drift',), present=True)
