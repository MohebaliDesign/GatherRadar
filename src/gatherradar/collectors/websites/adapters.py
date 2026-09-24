from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from ...domain.website import WebsiteConfig
from ..base import SourceConfigurationError, SourceUnavailableError
from .html import Node, content_text, excluded, parse_html
from .transport import Page
from .urls import detail_url

_EXCLUDES = ('.related', '#related', '.recommendations', '#recommendations',
             '.comments', '#comments', '.reviews', '#reviews', '.faq', '#faq', 'aside')


@dataclass(frozen=True)
class WebsiteDetail:
    text: str
    title: str
    external_id: str
    native_id: str | None
    links: tuple[str, ...]
    structured_data_present: bool


class WebsiteAdapter(Protocol):
    name: str

    def accepts(self, url: str, source_url: str) -> bool: ...
    def discover(self, page: Page, source_url: str) -> tuple[str, ...]: ...
    def extract(self, page: Page, source_url: str) -> WebsiteDetail: ...


class GenericAdapter:
    name = 'generic/1'
    native_ids = False

    def __init__(self, config: WebsiteConfig) -> None:
        self.config = config

    def accepts(self, url: str, source_url: str) -> bool:
        return detail_url(url, source_url, self.config.detail_path_prefixes, self.config.drop_query_params) is not None

    def discover(self, page: Page, source_url: str) -> tuple[str, ...]:
        urls: dict[str, None] = {}
        for node in parse_html(page.html).walk():
            if node.tag == 'a' and node.attrs.get('href'):
                url = detail_url(urljoin(page.url, node.attrs['href']), source_url,
                                 self.config.detail_path_prefixes, self.config.drop_query_params)
                if url:
                    urls[url] = None
        return tuple(urls)

    def regions(self, root: Node) -> list[Node]:
        def matching(node: Node):
            if self.skip(node):
                return
            if node.matches(self.config.content_selector):
                yield node
                return
            for child in node.children:
                if isinstance(child, Node):
                    yield from matching(child)
        regions = list(matching(root))
        if len(regions) != 1:
            raise SourceUnavailableError('expected exactly one detail content region')
        return regions

    def skip(self, node: Node) -> bool:
        return excluded(node, (*_EXCLUDES, *self.config.exclude_selectors))

    def extract(self, page: Page, source_url: str) -> WebsiteDetail:
        if not self.accepts(page.url, source_url):
            raise SourceUnavailableError('page is not an approved detail URL')
        root = parse_html(page.html)
        regions = self.regions(root)
        text = '\n'.join(part for node in regions if (part := content_text(node, self.skip)))
        if not text or len(text) > 100_000:
            raise SourceUnavailableError('missing or oversized detail text')
        # Inspect only retained nodes; hidden/review/profile links are never metadata.
        def retained(node: Node):
            if self.skip(node):
                return
            yield node
            for child in node.children:
                if isinstance(child, Node):
                    yield from retained(child)
        nodes = [node for region in regions for node in retained(region)]
        headings = [content_text(node, self.skip) for node in nodes if node.tag == 'h1']
        if len(headings) > 1:
            raise SourceUnavailableError('ambiguous detail headings')
        title = headings[0] if headings else text.splitlines()[0]
        links = []
        for node in nodes:
            if node.tag == 'a' and node.attrs.get('href'):
                url = urljoin(page.url, node.attrs['href'])
                parsed = urlsplit(url)
                if parsed.scheme in ('https', 'http') and parsed.hostname and not (parsed.username or parsed.password):
                    links.append(url)
        parts = urlsplit(page.url)
        native_id = parts.path.rstrip('/').rsplit('/', 1)[-1] if self.native_ids and not parts.query else None
        return WebsiteDetail(
            text, title, native_id or hashlib.sha256(page.url.encode('utf-8')).hexdigest(),
            native_id, tuple(dict.fromkeys(links)),
            any(node.tag == 'script' and node.attrs.get('type') == 'application/ld+json' for node in root.walk()),
        )


class DavvvatAdapter(GenericAdapter):
    name = 'davvvat/1'
    native_ids = True

    def regions(self, root: Node) -> list[Node]:
        # React's streamed SSR panel can sit inside a hidden staging wrapper
        # before its relocation script runs. Select only the observed detail
        # panel, never arbitrary hidden content or a whole-page fallback.
        regions = root.select(self.config.content_selector)
        if len(regions) != 1:
            raise SourceUnavailableError('Davvvat detail layout not recognized')
        return regions

    def skip(self, node: Node) -> bool:
        return (super().skip(node) or node.matches('.mobile-only') or node.matches('.event-detail-comments')
                or (node.tag == 'a' and node.attrs.get('href', '').startswith(('/profile', '/login'))))


class VadoostanAdapter(GenericAdapter):
    name = 'vadoostan/1'
    native_ids = True

    def regions(self, root: Node) -> list[Node]:
        main, = super().regions(root)
        # Public SSR detail content is in one direct container. Stop before FAQ,
        # rather than collecting collapsed policies and the organizer biography.
        containers = [child for child in main.children if isinstance(child, Node) and child.select('.font-black')]
        if len(containers) != 1:
            raise SourceUnavailableError('Vadoostan detail layout not recognized')
        kept = []
        for child in containers[0].children:
            if isinstance(child, Node) and child.matches('.font-black') and content_text(child) == 'سوالات متداول':
                break
            kept.append(child)
        return [Node('div', {}, kept)]

    def skip(self, node: Node) -> bool:
        return super().skip(node) or node.matches('.q-icon') or node.matches('.q-list') or node.matches('.q-card')


class JabamaAdapter(GenericAdapter):
    name = 'jabama-events/1'
    native_ids = True

    def regions(self, root: Node) -> list[Node]:
        articles = [node for node in root.select('article') if node.select('h1')]
        if len(articles) != 1:
            raise SourceUnavailableError('Jabama event detail layout not recognized')
        # Price is displayed in a separate booking aside. Retain only its visible
        # price paragraphs, never account/seat selection controls.
        article = articles[0]
        parents = [node for node in root.walk() if any(child is article for child in node.children)]
        asides = [child for parent in parents for child in parent.children
                  if isinstance(child, Node) and child.tag == 'aside']
        prices = []
        if len(asides) == 1 and any(
            content_text(button, lambda node: excluded(node) and node.tag != 'button') == 'خرید بلیت'
            for button in asides[0].select('button')
        ):
            prices = [node for node in asides[0].select('p') if 'تومان' in content_text(node)]
        # Ambiguous/moved panels lose price evidence instead of borrowing it from
        # another part of the page (which might advertise a different event).
        return [article, *prices] if len(prices) == 1 else [article]

    def skip(self, node: Node) -> bool:
        return (super().skip(node) or node.attrs.get('aria-labelledby') == 'event-reviews-heading'
                or node.attrs.get('id') == 'organizer'
                or (node.tag == 'p' and re.fullmatch(r'[\d٫.]+ از ۵ · [\d]+ نظر', content_text(node))))


ADAPTERS: dict[str, Callable[[WebsiteConfig], WebsiteAdapter]] = {
    'generic': GenericAdapter,
    'davvvat': DavvvatAdapter,
    'vadoostan': VadoostanAdapter,
    'jabama-events': JabamaAdapter,
}


def build_adapter(config: WebsiteConfig | None) -> WebsiteAdapter:
    if config is None:
        raise SourceConfigurationError('website source requires adapter configuration')
    factory = ADAPTERS.get(config.adapter)
    if factory is None:
        raise SourceConfigurationError('unknown website adapter key')
    return factory(config)
