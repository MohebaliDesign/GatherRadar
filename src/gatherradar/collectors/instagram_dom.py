from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

# Pure HTML extraction for the browser-backed Instagram collector. Everything here works
# on page HTML strings (Playwright's page.content()), so it is testable offline against
# local fixtures. Selection relies on URL patterns and semantic elements (a[href],
# article, h1, time[datetime], Open Graph meta), never on Instagram's generated CSS
# class names, which change frequently.

ORIGIN_POST = "post"
ORIGIN_REEL = "reel"

PROFILE_PRIVATE = "private"
PROFILE_UNAVAILABLE = "unavailable"
PROFILE_UNKNOWN = "unknown"

_INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com"})
_MEDIA_PATH = re.compile(
    r"^/(?:(?P<owner>[A-Za-z0-9._]+)/)?(?P<segment>p|reel)/(?P<shortcode>[A-Za-z0-9_-]+)/?$"
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
_NON_VISIBLE_TAGS = frozenset({"script", "style", "noscript", "template"})
_QUOTED_CAPTION = re.compile(r':\s*["“](?P<caption>.*)["”]\s*\.?\s*$', re.DOTALL)
# ‌ (zero-width non-joiner) is a normal part of Persian words and hashtags.
_HASHTAG = re.compile(r"#([\w‌]+)")
_MENTION = re.compile(r"@([A-Za-z0-9._]+)")

_PRIVATE_MARKERS = ("this account is private", "این حساب خصوصی است")
_UNAVAILABLE_MARKERS = ("sorry, this page isn't available", "این صفحه در دسترس نیست")


class MediaExtractionError(ValueError):
    """One media item could not be read; the rest of the run continues."""


class MalformedMediaPageError(MediaExtractionError):
    """A media page loaded but did not show recognizable content for the expected media."""


@dataclass(frozen=True, slots=True)
class MediaLink:
    shortcode: str
    kind: str
    url: str


@dataclass(frozen=True, slots=True)
class MediaPageData:
    caption: str | None
    caption_source: str
    published_at: datetime | None
    published_at_source: str
    image_url: str | None
    kind: str


@dataclass(frozen=True, slots=True)
class _TimeElement:
    value: str
    link_href: str | None
    in_article: bool


@dataclass(slots=True)
class _Document:
    hrefs: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    times: list[_TimeElement] = field(default_factory=list)
    headings: list[tuple[str, bool]] = field(default_factory=list)
    visible_text: str = ""


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.document = _Document()
        self._stack: list[tuple[str, dict[str, str]]] = []
        self._text: list[str] = []
        self._heading: list[str] | None = None
        self._heading_in_article = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "a" and attributes.get("href"):
            self.document.hrefs.append(attributes["href"])
        elif tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key and "content" in attributes:
                self.document.meta.setdefault(key, attributes["content"])
        elif tag == "time" and attributes.get("datetime"):
            self.document.times.append(
                _TimeElement(attributes["datetime"], self._nearest_link(), self._inside("article"))
            )
        elif tag == "br" and self._heading is not None:
            self._heading.append("\n")
        elif tag == "h1" and self._heading is None:
            self._heading = []
            self._heading_in_article = self._inside("article")

        if tag not in _VOID_TAGS:
            self._stack.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        if tag == "h1" and self._heading is not None:
            self._finish_heading()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in _NON_VISIBLE_TAGS for tag, _ in self._stack):
            return
        self._text.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def close(self) -> None:
        super().close()
        if self._heading is not None:
            self._finish_heading()
        self.document.visible_text = " ".join(" ".join(self._text).split())

    def _finish_heading(self) -> None:
        self.document.headings.append(("".join(self._heading or []), self._heading_in_article))
        self._heading = None

    def _nearest_link(self) -> str | None:
        for tag, attributes in reversed(self._stack):
            if tag == "a" and attributes.get("href"):
                return attributes["href"]
        return None

    def _inside(self, name: str) -> bool:
        return any(tag == name for tag, _ in self._stack)


def _parse(html: str) -> _Document:
    parser = _DocumentParser()
    parser.feed(html)
    parser.close()
    return parser.document


def parse_media_href(href: str, username: str | None = None) -> MediaLink | None:
    """Recognize an Instagram post or reel link (`/p/<code>/`, `/reel/<code>/`, or the
    owner-prefixed `/<username>/p/<code>/` form). When `username` is given, links
    explicitly owned by another account are rejected."""
    parsed = urlparse(href.strip())
    if parsed.scheme not in ("", "http", "https"):
        return None
    if parsed.netloc and parsed.netloc.lower() not in _INSTAGRAM_HOSTS:
        return None
    match = _MEDIA_PATH.match(parsed.path)
    if match is None:
        return None
    owner = match.group("owner")
    if username is not None and owner is not None and owner.lower() != username.strip().lower():
        return None
    segment = match.group("segment")
    shortcode = match.group("shortcode")
    return MediaLink(
        shortcode=shortcode,
        kind=ORIGIN_REEL if segment == "reel" else ORIGIN_POST,
        url=f"https://www.instagram.com/{segment}/{shortcode}/",
    )


def merge_media_links(*groups: Iterable[MediaLink]) -> list[MediaLink]:
    """One link per shortcode in first-seen order, preferring the reel form when the
    same media is linked both ways."""
    merged: dict[str, MediaLink] = {}
    for group in groups:
        for link in group:
            current = merged.get(link.shortcode)
            if current is None or (link.kind == ORIGIN_REEL and current.kind != ORIGIN_REEL):
                merged[link.shortcode] = link
    return list(merged.values())


def discover_media_links(html: str, username: str) -> list[MediaLink]:
    links = (parse_media_href(href, username) for href in _parse(html).hrefs)
    return merge_media_links(link for link in links if link is not None)


def detect_profile_state(html: str) -> str:
    """Read Instagram's visible private/unavailable notices (English or Persian UI).
    Script and style contents are ignored so bundled UI strings cannot match."""
    text = _parse(html).visible_text.lower().replace("’", "'")
    if any(marker in text for marker in _PRIVATE_MARKERS):
        return PROFILE_PRIVATE
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return PROFILE_UNAVAILABLE
    return PROFILE_UNKNOWN


def parse_media_page(html: str, link: MediaLink, *, final_url: str | None = None) -> MediaPageData:
    """Extract caption, publish time, and thumbnail from one post/reel page.

    Raises MalformedMediaPageError when the page shows different media or carries none
    of the expected caption, timestamp, or Open Graph evidence. Missing individual
    facts stay None rather than being guessed.
    """
    document = _parse(html)

    og_url = document.meta.get("og:url")
    og_link = parse_media_href(og_url) if og_url else None
    if og_link is not None and og_link.shortcode != link.shortcode:
        raise MalformedMediaPageError(
            f"media page for {link.shortcode} showed media {og_link.shortcode} instead"
        )

    caption, caption_source = _extract_caption(document)
    published_at, published_at_source = _extract_published_at(document, link.shortcode)
    image_url = document.meta.get("og:image") or None

    if caption is None and published_at is None and image_url is None and og_link is None:
        raise MalformedMediaPageError(
            f"media page for {link.shortcode} had no recognizable caption, timestamp, or metadata"
        )

    final_link = parse_media_href(final_url) if final_url else None
    is_reel = link.kind == ORIGIN_REEL or (final_link is not None and final_link.kind == ORIGIN_REEL)

    return MediaPageData(
        caption=caption,
        caption_source=caption_source,
        published_at=published_at,
        published_at_source=published_at_source,
        image_url=image_url,
        kind=ORIGIN_REEL if is_reel else ORIGIN_POST,
    )


def _extract_caption(document: _Document) -> tuple[str | None, str]:
    # Instagram renders a post caption as an h1; headings inside the media article win.
    for text, _in_article in sorted(document.headings, key=lambda heading: not heading[1]):
        if text.strip():
            return text.strip(), "h1"
    for key in ("og:description", "og:title"):
        match = _QUOTED_CAPTION.search(document.meta.get(key, ""))
        if match and match.group("caption").strip():
            return match.group("caption").strip(), key
    return None, "none"


def _extract_published_at(document: _Document, shortcode: str) -> tuple[datetime | None, str]:
    for element in document.times:
        link = parse_media_href(element.link_href) if element.link_href else None
        if link is not None and link.shortcode == shortcode:
            parsed = _parse_timestamp(element.value)
            if parsed is not None:
                return parsed, "time[datetime]:media-link"

    for element in document.times:
        # Comment timestamps link to /p/<code>/c/<id>/ permalinks; never use them.
        if element.in_article and not (element.link_href and "/c/" in element.link_href):
            parsed = _parse_timestamp(element.value)
            if parsed is not None:
                return parsed, "time[datetime]:article"

    return None, "none"


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def caption_hashtags(caption: str | None) -> tuple[str, ...]:
    return tuple(_HASHTAG.findall(caption or ""))


def caption_mentions(caption: str | None) -> tuple[str, ...]:
    return tuple(_MENTION.findall(caption or ""))


__all__ = [
    "ORIGIN_POST",
    "ORIGIN_REEL",
    "PROFILE_PRIVATE",
    "PROFILE_UNAVAILABLE",
    "PROFILE_UNKNOWN",
    "MediaExtractionError",
    "MalformedMediaPageError",
    "MediaLink",
    "MediaPageData",
    "parse_media_href",
    "merge_media_links",
    "discover_media_links",
    "detect_profile_state",
    "parse_media_page",
    "caption_hashtags",
    "caption_mentions",
]
