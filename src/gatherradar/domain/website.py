from __future__ import annotations

import re
from dataclasses import dataclass

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
