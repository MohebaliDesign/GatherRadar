from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain import RawItem, Source, SourceType, compute_content_hash
from .base import (
    AuthenticationRequiredError,
    CollectionResult,
    ItemFailure,
    SourceAccessRestrictedError,
    SourceConfigurationError,
    SourceDisabledError,
    SourceTypeMismatchError,
    SourceUnavailableError,
)
from .instagram_auth import (
    NO_ACTIVE_SESSION_MESSAGE,
    SessionInvalidError,
    SessionNotFoundError,
    load_active_authenticated_loader,
)

COLLECTOR_VERSION = "instagram-instaloader/2"
DEFAULT_LIMIT = 5

ORIGIN_POST = "post"
ORIGIN_REEL = "reel"

# Instagram's anonymous web timeline exposes only the legacy `__typename`, which
# carries no "clips" marker, so a plain video post can't be told apart from a reel by
# typename alone. When the collection path fetched an item through get_reels() it
# already knows the origin, so that trusted context is used instead (see content_type_for).
_TYPENAME_TO_CONTENT_TYPE = {
    "GraphImage": "image",
    "GraphVideo": "video",
    "GraphSidecar": "carousel",
}
UNKNOWN_CONTENT_TYPE = "unknown"

PostFetcher = Callable[[str, int], Iterable[tuple[str, Any]]]


def build_raw_item_id(username: str, shortcode: str) -> str:
    """Stable observation identity: source identity plus the Instagram shortcode."""
    return f"instagram:{username.strip().lower()}:{shortcode.strip()}"


def build_content_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode.strip()}/"


def content_type_for(typename: str | None, *, origin: str = ORIGIN_POST) -> str:
    if origin == ORIGIN_REEL:
        return "reel"
    return _TYPENAME_TO_CONTENT_TYPE.get(typename or "", UNKNOWN_CONTENT_TYPE)


def _attribute(post: Any, name: str, default: Any = None) -> Any:
    # Instaloader properties raise assorted KeyError/InstaloaderException types when
    # a field is missing from the timeline node, so degrade instead of losing a post
    # over one optional field.
    try:
        value = getattr(post, name)
    except Exception:
        return default
    return default if value is None else value


def _to_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [entry for entry in value if isinstance(entry, str) and entry.strip()]


def map_post_to_raw_item(
    post: Any, source: Source, captured_at: datetime, *, origin: str = ORIGIN_POST
) -> RawItem:
    """Convert one Instaloader post (from either posts or reels) into the shared
    RawItem contract."""
    shortcode = _attribute(post, "shortcode")
    if not isinstance(shortcode, str) or not shortcode.strip():
        raise ValueError("post is missing a shortcode")
    shortcode = shortcode.strip()

    username = (source.username or "").strip()
    if not username:
        raise SourceConfigurationError(f"source {source.id} has no Instagram username")

    caption = _attribute(post, "caption", "")
    raw_text = caption if isinstance(caption, str) else ""
    media_id = _attribute(post, "mediaid")
    typename = _attribute(post, "typename")
    typename = typename if isinstance(typename, str) else None
    is_video = _attribute(post, "is_video")

    content_type = content_type_for(typename, origin=origin)
    content_url = build_content_url(shortcode)
    published_at = _to_utc(_attribute(post, "date_utc"))

    raw_metadata: dict[str, Any] = {
        "collector_version": COLLECTOR_VERSION,
        "origin": origin,
        "typename": typename,
        "media_id": str(media_id) if media_id is not None else None,
        "is_video": bool(is_video) if isinstance(is_video, bool) else None,
        "hashtags": _string_list(_attribute(post, "caption_hashtags", [])),
        "mentions": _string_list(_attribute(post, "caption_mentions", [])),
    }

    image_url = _attribute(post, "url")

    return RawItem(
        id=build_raw_item_id(username, shortcode),
        source_id=source.id,
        source_type=SourceType.INSTAGRAM,
        external_id=shortcode,
        content_type=content_type,
        content_url=content_url,
        raw_text=raw_text,
        captured_at=captured_at,
        published_at=published_at,
        author=_attribute(post, "owner_username", username) or username,
        image_url=image_url if isinstance(image_url, str) and image_url.strip() else None,
        content_hash=compute_content_hash(
            raw_text=raw_text,
            published_at=published_at,
            content_url=content_url,
        ),
        raw_metadata=raw_metadata,
    )


def _recency_sort_key(entry: tuple[str, Any]) -> tuple[int, float]:
    """Items with a reliable timestamp sort newest-first; items without one sort last,
    keeping their original relative order."""
    _, post = entry
    published = _to_utc(_attribute(post, "date_utc"))
    if published is None:
        return (1, 0.0)
    return (0, -published.timestamp())


def _dedupe_and_bound(
    candidates: Iterable[tuple[str, Any]], limit: int
) -> list[tuple[str, Any]]:
    """Collapse the same media collected through both posts and reels into one
    observation, preferring the Reel origin whichever order it was seen in so it is
    classified as `reel`, not `video`; bounded to `limit` total items in the order
    the candidates were sorted (newest first). A post missing a shortcode is never
    treated as a duplicate; it passes through so the mapper can raise its own
    per-item failure."""
    chosen: dict[str, tuple[str, Any]] = {}
    order: list[str | tuple[str, Any]] = []
    for origin, post in candidates:
        shortcode = _attribute(post, "shortcode")
        if isinstance(shortcode, str) and shortcode.strip():
            key = shortcode.strip()
            if key not in chosen:
                chosen[key] = (origin, post)
                order.append(key)
            elif origin == ORIGIN_REEL and chosen[key][0] != ORIGIN_REEL:
                chosen[key] = (origin, post)
        else:
            order.append((origin, post))

    bounded: list[tuple[str, Any]] = []
    for entry in order:
        if len(bounded) >= limit:
            break
        bounded.append(chosen[entry] if isinstance(entry, str) else entry)
    return bounded


class InstagramCollector:
    """Collects a bounded number of recent public posts and reels for one Instagram source."""

    def __init__(
        self,
        *,
        fetch_posts: PostFetcher | None = None,
        now: Callable[[], datetime] | None = None,
        data_dir: str | Path = "data",
    ) -> None:
        self._fetch_posts = (
            fetch_posts
            if fetch_posts is not None
            else InstaloaderPostFetcher(data_dir=data_dir)
        )
        self._now = now if now is not None else (lambda: datetime.now(timezone.utc))

    def collect(self, source: Source, *, limit: int = DEFAULT_LIMIT) -> CollectionResult:
        self._validate(source, limit)
        captured_at = self._now()

        items: list[RawItem] = []
        failures: list[ItemFailure] = []

        # Access errors raised by the fetcher propagate so a blocked run stops
        # cleanly. Only per-item mapping errors are isolated here.
        candidates = sorted(
            self._fetch_posts(source.username or "", limit), key=_recency_sort_key
        )
        for origin, post in _dedupe_and_bound(candidates, limit):
            try:
                items.append(map_post_to_raw_item(post, source, captured_at, origin=origin))
            except Exception as exc:
                failures.append(
                    ItemFailure(
                        reason=f"{type(exc).__name__}: {exc}",
                        external_id=_attribute(post, "shortcode"),
                    )
                )

        return CollectionResult(
            source_id=source.id,
            items=tuple(items),
            failures=tuple(failures),
        )

    @staticmethod
    def _validate(source: Source, limit: int) -> None:
        if source.source_type is not SourceType.INSTAGRAM:
            raise SourceTypeMismatchError(
                f"source {source.id} is a {source.source_type.value} source, "
                "not an Instagram source"
            )
        if not source.enabled:
            raise SourceDisabledError(f"source {source.id} is disabled in the registry")
        if not (source.username or "").strip():
            raise SourceConfigurationError(f"source {source.id} has no Instagram username")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")


class InstaloaderPostFetcher:
    """Reads recent public posts and reels through the active authenticated
    Instaloader session, without downloading media.

    The active session belongs to whichever Instagram account the owner
    authenticated as (see `python -m gatherradar auth instagram`); it is loaded
    independently of `username`, the public source profile being crawled, so one
    login account can be reused across every approved source. Anonymous access is
    not used: it is known to be blocked (HTTP 429) for this project's sources, so a
    missing or invalid local session is reported clearly instead of silently
    attempting repeated anonymous requests.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = "data",
        request_timeout: float = 30.0,
        max_connection_attempts: int = 1,
        load_session: Callable[[], Any] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._request_timeout = request_timeout
        # A single attempt means a rejected request (e.g. HTTP 429) is reported
        # immediately instead of triggering Instaloader's own long rate-limit backoff.
        self._max_connection_attempts = max_connection_attempts
        self._load_session = load_session if load_session is not None else self._load_session_default

    def _load_session_default(self) -> Any:
        return load_active_authenticated_loader(data_dir=self._data_dir)

    def __call__(self, username: str, limit: int) -> Iterator[tuple[str, Any]]:
        import instaloader
        from instaloader import exceptions as instaloader_errors

        try:
            loader = self._load_session()
        except SessionNotFoundError as exc:
            raise AuthenticationRequiredError(NO_ACTIVE_SESSION_MESSAGE) from exc
        except SessionInvalidError as exc:
            raise AuthenticationRequiredError(
                f"the active Instagram session is no longer valid ({exc}); "
                "run 'python -m gatherradar auth instagram' again to refresh it"
            ) from exc

        loader.context.max_connection_attempts = self._max_connection_attempts
        loader.context.request_timeout = self._request_timeout

        try:
            profile = instaloader.Profile.from_username(loader.context, username)
            if profile.is_private:
                raise SourceAccessRestrictedError(
                    f"Instagram profile @{username} is private; "
                    "GatherRadar collects public content only"
                )
            yield from _tagged(profile.get_posts(), ORIGIN_POST, limit)
            yield from _tagged(profile.get_reels(), ORIGIN_REEL, limit)
        except instaloader_errors.InstaloaderException as exc:
            raise _translate_instaloader_error(username, exc) from exc


def _tagged(posts: Iterable[Any], origin: str, limit: int) -> Iterator[tuple[str, Any]]:
    for index, post in enumerate(posts):
        if index >= limit:
            break
        yield origin, post


def _looks_rate_limited(exc: Exception) -> bool:
    # Once Instaloader exhausts its retries it re-raises a plain ConnectionException
    # that still carries the original 429 text, so the status has to be read back out.
    text = str(exc).lower()
    return "429" in text or "too many requests" in text


def _translate_instaloader_error(username: str, exc: Exception) -> SourceUnavailableError:
    from instaloader import exceptions as errors

    if isinstance(exc, errors.ProfileNotExistsException):
        return SourceUnavailableError(
            f"Instagram profile @{username} was not found or is unavailable"
        )
    if isinstance(exc, errors.PrivateProfileNotFollowedException):
        return SourceAccessRestrictedError(
            f"Instagram profile @{username} is private; GatherRadar collects public content only"
        )
    if isinstance(exc, errors.TooManyRequestsException) or _looks_rate_limited(exc):
        # Report only what is actually known: Instagram returned HTTP 429 for this
        # request. That may reflect rate limiting or access policy; it does not by
        # itself prove an IP-level block, so no root cause is inferred here.
        return SourceAccessRestrictedError(
            f"Instagram refused the request with HTTP 429 (Too Many Requests): {exc}"
        )
    if isinstance(exc, (errors.LoginRequiredException, errors.QueryReturnedForbiddenException)):
        return SourceAccessRestrictedError(
            "Instagram refused anonymous access and asked for a logged-in session"
        )
    if isinstance(exc, errors.ConnectionException):
        return SourceUnavailableError(f"Could not reach Instagram: {exc}")
    return SourceUnavailableError(f"Instagram collection failed: {type(exc).__name__}: {exc}")
