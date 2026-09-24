from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable

from ..domain import RawItem, Source, SourceType, compute_content_hash
from .base import (CollectionResult, ItemFailure, SourceAccessRestrictedError, SourceDisabledError,
                   SourceTypeMismatchError, SourceUnavailableError)
from .websites.adapters import WebsiteAdapter, build_adapter
from .websites.transport import HttpTransport, Page, PageTransport
from .websites.urls import canonical_url


class WebsiteCollector:
    """Shared bounded list/detail collection; adapters own all layout decisions."""

    def __init__(self, *, transport: PageTransport | None = None,
                 adapter: WebsiteAdapter | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        self._transport = transport
        self._adapter = adapter
        self._now = now or (lambda: datetime.now(timezone.utc))

    def collect(self, source: Source, *, limit: int) -> CollectionResult:
        validate_website_source(source, limit)
        adapter = self._adapter or build_adapter(source.website)
        transport = self._transport or HttpTransport(source.url)
        listing = transport.fetch(source.url)
        canonical_url(listing.url, source.url)
        urls = adapter.discover(listing, source.url)
        if not urls:
            raise SourceUnavailableError('no supported detail links in public listing')
        items: list[RawItem] = []
        failures: list[ItemFailure] = []
        seen: set[str] = set()
        for index, url in enumerate(urls[:min(limit * 3, 30)], 1):
            try:
                canonical_url(url, source.url)
                if not adapter.accepts(url, source.url):
                    raise SourceUnavailableError('adapter returned an invalid detail URL')
                page = transport.fetch(url, allowed=lambda target: adapter.accepts(target, source.url))
                canonical = canonical_url(page.url, source.url, source.website.drop_query_params if source.website else ())
                # Enforce final origin/layout even with a replacement transport.
                if not adapter.accepts(canonical, source.url):
                    raise SourceUnavailableError('final URL is not a supported detail')
                detail = adapter.extract(Page(canonical, page.html, page.transport), source.url)
                identity = f'website:{source.id}:{detail.external_id}'
                if identity in seen:
                    continue
                item = RawItem(
                    id=identity, source_id=source.id, source_type=SourceType.WEBSITE,
                    external_id=detail.external_id, content_type='webpage',
                    content_url=canonical, raw_text=detail.text, captured_at=self._now(),
                    published_at=None,
                    content_hash=compute_content_hash(raw_text=detail.text, published_at=None, content_url=canonical),
                    raw_metadata={
                        'adapter': adapter.name, 'list_url': listing.url, 'detail_url': canonical,
                        'page_title': detail.title, 'native_id': detail.native_id,
                        'structured_data_present': detail.structured_data_present,
                        'content_links': list(detail.links), 'transport': page.transport,
                    },
                )
                items.append(item)
                seen.add(identity)
                if len(items) == limit:
                    break
            except Exception as exc:
                failures.append(ItemFailure(f'detail {index}: collection failed ({type(exc).__name__})'))
                if isinstance(exc, SourceAccessRestrictedError):
                    # Stop this source on rate limits/access refusals; preserve
                    # earlier successes without probing additional pages.
                    break
        return CollectionResult(source.id, tuple(items), tuple(failures))


def validate_website_source(source: Source, limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise ValueError('website limit must be an integer between 1 and 30')
    if source.source_type is not SourceType.WEBSITE:
        raise SourceTypeMismatchError('source is not a website')
    if not source.enabled:
        raise SourceDisabledError('website source is disabled')
