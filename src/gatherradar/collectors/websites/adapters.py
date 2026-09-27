from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from ...domain.website import MAX_CARD_TEXT, WebsiteConfig
from ..base import SourceConfigurationError, SourceUnavailableError
from .html import Node, content_text, excluded, parse_html
from .transport import Page
from .urls import detail_url

_EXCLUDES = ('.related', '#related', '.recommendations', '#recommendations',
             '.comments', '#comments', '.reviews', '#reviews', '.faq', '#faq', 'aside')
# An explicit length, e.g. "۳ ساعت" or "۲ ساعت و نیم"; never a clock time.
_DURATION = r'[0-9۰-۹]+(?:[.٫/][0-9۰-۹]+)?\s*(?:ساعت|دقیقه)(?:\s*و\s*نیم)?'
DURATION_RE = re.compile(_DURATION)

Fields = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class WebsiteDetail:
    text: str
    title: str
    external_id: str
    native_id: str | None
    links: tuple[str, ...]
    structured_data_present: bool
    title_is_heading: bool = False
    # Adapter-verified (field, exact retained text) pairs from page structure.
    fields: Fields = ()


@dataclass(frozen=True)
class ListingCard:
    """One item's own card on the listing page: its anchor's visible text only."""

    text: str
    fields: Fields = ()


class WebsiteAdapter(Protocol):
    name: str

    def accepts(self, url: str, source_url: str) -> bool: ...
    def discover(self, page: Page, source_url: str) -> tuple[str, ...]: ...
    def cards(self, page: Page, source_url: str) -> dict[str, ListingCard]: ...
    def extract(self, page: Page, source_url: str) -> WebsiteDetail: ...


def _verified(fields: Fields, text: str) -> Fields:
    """Keep only structural values that are exact, bounded slices of retained text."""
    return tuple(dict.fromkeys((name, value) for name, value in fields
                               if value and value.strip() and value in text))


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

    def cards(self, page: Page, source_url: str) -> dict[str, ListingCard]:
        """Per-item card evidence: exactly the linking anchor's own subtree.

        The listing page is never concatenated. A URL linked by differing card
        texts (e.g. a featured strip and a list) is ambiguous and gets no card.
        """
        found: dict[str, set[ListingCard]] = {}
        for node in parse_html(page.html).walk():
            if node.tag != 'a' or not node.attrs.get('href'):
                continue
            url = detail_url(urljoin(page.url, node.attrs['href']), source_url,
                             self.config.detail_path_prefixes, self.config.drop_query_params)
            if url is None:
                continue
            text = content_text(node, self.skip)
            if not text:
                continue  # Image-only links add no evidence and no ambiguity.
            # An oversized "card" is a wrapper, not one item's evidence: poison it.
            card = (ListingCard(text, _verified(self.card_fields(node), text))
                    if len(text) <= MAX_CARD_TEXT else ListingCard(''))
            found.setdefault(url, set()).add(card)
        return {url: card for url, cards in found.items()
                if len(cards) == 1 and (card := next(iter(cards))).text}

    def card_fields(self, card: Node) -> Fields:
        return ()

    def detail_fields(self, root: Node, regions: list[Node]) -> Fields:
        return ()

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
        headings = self.headings(nodes)
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
            bool(headings), _verified(self.detail_fields(root, regions), text),
        )

    def headings(self, nodes: list[Node]) -> list[str]:
        return [content_text(node, self.skip) for node in nodes if node.tag == 'h1']


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
    name = 'vadoostan/2'
    native_ids = True

    def headings(self, nodes: list[Node]) -> list[str]:
        # This adapter's retained detail region starts with its explicit title
        # heading, followed by labelled description/FAQ sections.
        headings = [content_text(node,self.skip) for node in nodes if node.matches('.font-black')]
        return headings[:1] if headings and headings[0] not in {'توضیحات','سوالات متداول'} else []

    def _container(self, root: Node) -> Node:
        main, = super().regions(root)
        containers = [child for child in main.children if isinstance(child, Node) and child.select('.font-black')]
        if len(containers) != 1:
            raise SourceUnavailableError('Vadoostan detail layout not recognized')
        return containers[0]

    def regions(self, root: Node) -> list[Node]:
        # Public SSR detail content is in one direct container. Stop before FAQ,
        # rather than collecting collapsed policies and the organizer biography.
        # After it, only the organizer's explicit name/caption-label pair is kept.
        container = self._container(root)
        kept = []
        for child in container.children:
            if isinstance(child, Node) and child.matches('.font-black') and content_text(child) == 'سوالات متداول':
                break
            kept.append(child)
        return [Node('div', {}, kept + self._organizers(container))]

    def _organizers(self, container: Node) -> list[Node]:
        return [section for card in container.select('.q-card')
                for section in card.select('.q-item__section--main')
                if [_folded(content_text(n)) for n in section.select('.q-item__label--caption')]
                in (['برگزار کننده'], ['برگزارکننده'])]

    def detail_fields(self, root: Node, regions: list[Node]) -> Fields:
        container = self._container(root)
        children = [child for child in container.children if isinstance(child, Node)]
        fields: list[tuple[str, str]] = []
        titles = [i for i, child in enumerate(children) if child.matches('.font-black')]
        if titles and titles[0] + 1 < len(children):
            # Observed header: date/time · locality · length. The listing card
            # labels the same locality value "محله". Any other shape yields nothing.
            slots = [text for child in children[titles[0] + 1].children if isinstance(child, Node)
                     and (text := content_text(child, self.skip))]
            if len(slots) >= 2 and re.search(r'[0-9۰-۹]', slots[0]):
                # The first slot is this item's scheduled (first) session.
                fields.append(('source_date_text', slots[0]))
                lengths = [s for s in slots[1:] if DURATION_RE.fullmatch(s)]
                others = [s for s in slots[1:] if not DURATION_RE.fullmatch(s)]
                if len(lengths) == 1:
                    fields.append(('duration_text', lengths[0]))
                if len(others) == 1 and len(others[0]) <= 120 and not DURATION_RE.search(others[0]):
                    fields.append(('area_text', others[0]))
        for index, child in enumerate(children[:-1]):
            if child.matches('.font-black') and content_text(child) == 'توضیحات':
                if description := content_text(children[index + 1], self.skip):
                    fields.append(('description_text', description))
                break
        names = [content_text(label) for section in self._organizers(container)
                 for label in section.select('.q-item__label')
                 if not label.matches('.q-item__label--caption')]
        # Co-organizers would need a list contract; one explicit name only.
        if len(names) == 1 and names[0]:
            fields.append(('organizer_name', names[0]))
        return tuple(fields)

    def card_fields(self, card: Node) -> Fields:
        # Card meta: an explicit "محله:" label, and one status badge that holds
        # either the ticket price or availability wording (e.g. تکمیل ظرفیت).
        fields: list[tuple[str, str]] = []
        areas = [match.group(1).strip() for node in card.walk() for part in node.children
                 if isinstance(part, str) and (match := re.fullmatch(r'\s*محله\s*:\s*(.+?)\s*', part))]
        if len(areas) == 1:
            fields.append(('area_text', areas[0]))
        badges = [text for node in card.walk()
                  if {'rounded', 'font-bold', 'px-2'} <= set(node.attrs.get('class', '').split())
                  and (text := content_text(node, self.skip))]
        if len(badges) == 1:
            priced = any(unit in badges[0] for unit in ('تومان', 'ریال', 'رایگان'))
            fields.append(('price_text' if priced else 'availability_text', badges[0]))
        # Observed genre chip (e.g. بازی, ورزش): the card's own leading square
        # label. One short word-only label, else nothing.
        chips = [text for child in card.children if isinstance(child, Node)
                 and {'shrink-0', 'font-extrabold'} <= set(child.attrs.get('class', '').split())
                 and (text := content_text(child, self.skip))]
        if len(chips) == 1 and len(chips[0]) <= 40 and not re.search(r'[0-9۰-۹:]', chips[0]):
            fields.append(('source_category_text', chips[0]))
        return tuple(fields)

    def skip(self, node: Node) -> bool:
        return super().skip(node) or node.matches('.q-icon') or node.matches('.q-list') or node.matches('.q-card')


class JabamaAdapter(GenericAdapter):
    """Jabama detail pages, shared by its Events and Experiences listings."""

    name = 'jabama-events/2'
    native_ids = True

    def _article(self, root: Node) -> Node:
        articles = [node for node in root.select('article') if node.select('h1')]
        if len(articles) != 1:
            raise SourceUnavailableError('Jabama event detail layout not recognized')
        return articles[0]

    def _prices(self, root: Node, article: Node) -> list[Node]:
        # Price is displayed in a separate booking aside. Retain only its visible
        # price paragraph, never account/seat selection controls. Ambiguous or
        # moved panels lose price evidence instead of borrowing it from another
        # part of the page (which might advertise a different event).
        parents = [node for node in root.walk() if any(child is article for child in node.children)]
        asides = [child for parent in parents for child in parent.children
                  if isinstance(child, Node) and child.tag == 'aside']
        prices = []
        if len(asides) == 1 and any(
            content_text(button, lambda node: excluded(node) and node.tag != 'button') == 'خرید بلیت'
            for button in asides[0].select('button')
        ):
            prices = [node for node in asides[0].select('p') if 'تومان' in content_text(node)]
        return prices if len(prices) == 1 else []

    def regions(self, root: Node) -> list[Node]:
        # The host section contributes only its label and name, never its link.
        article = self._article(root)
        return [article, *self._organizer(article), *self._prices(root, article)]

    def _organizer(self, article: Node) -> list[Node]:
        sections = [node for node in article.select('section') if node.attrs.get('id') == 'organizer']
        if len(sections) != 1:
            return []
        labels = [child for child in sections[0].children if isinstance(child, Node) and child.tag == 'p']
        names = sections[0].select('h3')
        if (len(labels) == 1 and len(names) == 1 and content_text(names[0])
                and _folded(content_text(labels[0])) in {'میزبان', 'برگزار کننده', 'برگزارکننده'}):
            return [labels[0], names[0]]
        return []

    def detail_fields(self, root: Node, regions: list[Node]) -> Fields:
        article = self._article(root)
        fields: list[tuple[str, str]] = []
        abouts = [section for section in article.select('section')
                  if (heads := section.select('h2')) and _folded(content_text(heads[0])).startswith('درباره این')]
        bodies = [node for section in abouts for node in section.select('.rich-text-content')]
        if len(bodies) == 1 and (description := content_text(bodies[0], self.skip)):
            fields.append(('description_text', description))
        if organizer := self._organizer(article):
            fields.append(('organizer_name', content_text(organizer[1])))
        for price in self._prices(root, article):
            fields.append(('price_text', content_text(price)))
        # Header tile marked by the clock icon: a leading explicit length only,
        # never its date, weekday schedule or trailing category word.
        lengths = [length for tile in article.walk()
                   if [c.attrs.get('class', '') for c in tile.children if isinstance(c, Node) and c.tag == 'svg']
                   and 'lucide-clock' in next(c.attrs.get('class', '') for c in tile.children
                                              if isinstance(c, Node) and c.tag == 'svg')
                   for p in tile.children if isinstance(p, Node) and p.tag == 'p'
                   if (length := _leading_duration(content_text(p)))]
        if len(lengths) == 1:
            fields.append(('duration_text', lengths[0]))
        return tuple(fields)

    def card_fields(self, card: Node) -> Fields:
        fields: list[tuple[str, str]] = []
        lengths = [length for row in card.select('div') if 'flex-wrap' in row.attrs.get('class', '').split()
                   for span in row.children if isinstance(span, Node) and not excluded(span)
                   if (length := _leading_duration(content_text(span)))]
        if len(lengths) == 1:
            fields.append(('duration_text', lengths[0]))
        # The card's price row: one baseline-aligned group of price spans.
        prices = [text for node in card.select('span') if 'items-baseline' in node.attrs.get('class', '').split()
                  and (text := content_text(node, self.skip))
                  and any(unit in text for unit in ('تومان', 'ریال', 'رایگان'))]
        if len(prices) == 1:
            fields.append(('price_text', prices[0]))
        return tuple(fields)

    def skip(self, node: Node) -> bool:
        return (super().skip(node) or node.attrs.get('aria-labelledby') == 'event-reviews-heading'
                or node.attrs.get('id') == 'organizer'
                or (node.tag == 'p' and re.fullmatch(r'[\d٫.]+ از ۵ · [\d]+ نظر', content_text(node))))


def _folded(text: str) -> str:
    return ' '.join(text.replace('‌', ' ').split())


def _leading_duration(text: str) -> str | None:
    text = text.strip()
    match = DURATION_RE.match(text)
    if match is None or (match.end() < len(text) and not text[match.end()].isspace()):
        return None
    return match.group(0)


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
