from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

# Facts an adapter may read from explicit page structure (a labelled section,
# a fixed header slot, a caption label). Values are exact retained source text.
STRUCTURED_FIELDS = frozenset({
    'description_text', 'area_text', 'duration_text', 'organizer_name', 'availability_text',
    'price_text', 'source_date_text', 'source_category_text',
})
# Where a structured value was observed: the item's own detail page, or its own
# listing card on the approved listing page.
FIELD_ORIGINS = ('detail', 'listing')
MAX_CARD_TEXT = 1500
SESSION_UNVERIFIED_PROPERTIES = 'unverified_properties'


@dataclass(frozen=True, slots=True)
class SourceSession:
    """Whitelisted facts from one public website session, before normalization.

    The source's ISO spelling and separate price keys are retained. No currency,
    end time, event-level price or availability is inferred by the collector.
    ``source_locator`` identifies the precise embedded-data path on the detail URL.
    """

    source_session_id: str
    source_event_id: str
    start_iso: str
    source_locator: str
    duration_hours: str | None = None
    price_per_person: str | None = None
    unit_price: str | None = None
    host_discount_pct: str | None = None
    platform_discount_pct: str | None = None
    remaining_seats: int | None = None
    enabled: bool | None = None
    # None for the documented shape. "unverified_properties" when the session also
    # carried properties whose meaning was not inspected: only its identity, start
    # and duration were kept, and it is never actionable until reviewed.
    schema_status: str | None = None

    def __post_init__(self) -> None:
        if self.schema_status not in (None, SESSION_UNVERIFIED_PROPERTIES):
            raise ValueError('invalid source session schema status')
        for value in (self.source_session_id, self.source_event_id):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
                raise ValueError('invalid source session identity')
        if (not isinstance(self.source_locator, str)
                or not re.fullmatch(r'react-router:loaderData/routes/events\.\$id/sessions/[0-9]{1,3}',
                                    self.source_locator)):
            raise ValueError('invalid source session locator')
        if (not isinstance(self.start_iso, str) or len(self.start_iso) > 40
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})',
                                    self.start_iso)):
            raise ValueError('invalid source session timestamp')
        try:
            instant = datetime.fromisoformat(self.start_iso.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('invalid source session timestamp') from exc
        if instant.utcoffset() is None:
            raise ValueError('source session timestamp requires an offset')
        for name in ('duration_hours', 'price_per_person', 'unit_price',
                     'host_discount_pct', 'platform_discount_pct'):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,15}(?:\.[0-9]{1,6})?', value):
                raise ValueError('invalid source session numeric fact')
            try:
                amount = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError('invalid source session numeric fact') from exc
            if name == 'duration_hours' and not Decimal(0) < amount <= Decimal(744):
                raise ValueError('invalid source session duration')
            if name.endswith('_discount_pct') and amount > 100:
                raise ValueError('invalid source session discount')
        if (self.remaining_seats is not None
                and (type(self.remaining_seats) is not int or not 0 <= self.remaining_seats <= 1_000_000)):
            raise ValueError('invalid source session remaining seats')
        if self.enabled is not None and type(self.enabled) is not bool:
            raise ValueError('invalid source session enabled flag')

    def to_dict(self) -> dict[str, object]:
        # schema_status is omitted when unset so documented sessions serialize,
        # and therefore hash, exactly as before it existed.
        return {name: getattr(self, name) for name in self.__dataclass_fields__
                if name != 'schema_status' or self.schema_status is not None}

    @classmethod
    def from_mapping(cls, value: object) -> SourceSession:
        if not isinstance(value, dict) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError('invalid source session mapping')
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError('invalid source session mapping') from exc


@dataclass(frozen=True, slots=True)
class WebsiteConfig:
    """Small list/detail configuration; selectors are tag, .class, or #id only."""

    adapter: str = 'generic'
    detail_path_prefixes: tuple[str, ...] = ()
    content_selector: str = 'article'
    exclude_selectors: tuple[str, ...] = ()
    drop_query_params: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', self.adapter):
            raise ValueError('invalid website adapter key')
        for name in ('detail_path_prefixes', 'exclude_selectors', 'drop_query_params'):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(not isinstance(x, str) or not x for x in value):
                raise ValueError(f'website {name} must be a sequence of nonempty strings')
        if not self.detail_path_prefixes or any(
            not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)+', prefix)
            for prefix in self.detail_path_prefixes
        ):
            raise ValueError('website detail_path_prefixes must contain absolute directory paths')
        for selector in (self.content_selector, *self.exclude_selectors):
            if not isinstance(selector, str) or not re.fullmatch(r'[.#]?[A-Za-z_][A-Za-z0-9_-]*', selector):
                raise ValueError('website selectors support only tag, .class, or #id')
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+', key) for key in self.drop_query_params):
            raise ValueError('invalid website drop_query_params')

    @classmethod
    def from_mapping(cls, value: object) -> WebsiteConfig:
        if not isinstance(value, dict) or set(value) - cls.__dataclass_fields__.keys():
            raise ValueError('invalid website configuration')
        options = dict(value)
        for name in ('detail_path_prefixes', 'exclude_selectors', 'drop_query_params'):
            if name in options:
                if not isinstance(options[name], list):
                    raise ValueError(f'website {name} must be a list')
                options[name] = tuple(options[name])
        return cls(**options)
