from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from typing import Any

from ..domain import RawItem, Source, SourceType
from .base import (
    CollectionResult,
    ItemFailure,
    SourceAccessRestrictedError,
    SourceConfigurationError,
    SourceDisabledError,
    SourceTypeMismatchError,
    SourceUnavailableError,
)

COLLECTOR_VERSION = "instagram-instaloader/1"
DEFAULT_LIMIT = 5

# Instagram's anonymous web timeline exposes only the legacy `__typename`, which
# carries no "clips" marker. Reels are therefore recorded as `video` rather than
# guessed at.
_TYPENAME_TO_CONTENT_TYPE = {
    "GraphImage": "image",
    "GraphVideo": "video",
    "GraphSidecar": "carousel",
}
UNKNOWN_CONTENT_TYPE = "unknown"

PostFetcher = Callable[[str, int], Iterable[Any]]


def build_raw_item_id(username: str, shortcode: str) -> str:
    """Stable observation identity: source identity plus the Instagram shortcode."""
    return f"instagram:{username.strip().lower()}:{shortcode.strip()}"


def build_content_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode.strip()}/"


def content_type_for(typename: str | None) -> str:
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


def map_post_to_raw_item(post: Any, source: Source, captured_at: datetime) -> RawItem:
    """Convert one Instaloader post into the shared RawItem contract."""
    shortcode = _attribute(post, "shortcode")
    if not isinstance(shortcode, str) or not shortcode.strip():
        raise ValueError("post is missing a shortcode")
    shortcode = shortcode.strip()

    username = (source.username or "").strip()
    if not username:
        raise SourceConfigurationError(f"source {source.id} has no Instagram username")

    caption = _attribute(post, "caption", "")
    media_id = _attribute(post, "mediaid")
    typename = _attribute(post, "typename")
    typename = typename if isinstance(typename, str) else None
    is_video = _attribute(post, "is_video")

    raw_metadata: dict[str, Any] = {
        "collector_version": COLLECTOR_VERSION,
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
        content_type=content_type_for(typename),
        content_url=build_content_url(shortcode),
        raw_text=caption if isinstance(caption, str) else "",
        captured_at=captured_at,
        published_at=_to_utc(_attribute(post, "date_utc")),
        author=_attribute(post, "owner_username", username) or username,
        image_url=image_url if isinstance(image_url, str) and image_url.strip() else None,
        raw_metadata=raw_metadata,
    )


class InstagramCollector:
    """Collects a bounded number of recent public posts for one Instagram source."""

    def __init__(
        self,
        *,
        fetch_posts: PostFetcher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetch_posts = fetch_posts if fetch_posts is not None else InstaloaderPostFetcher()
        self._now = now if now is not None else (lambda: datetime.now(timezone.utc))

    def collect(self, source: Source, *, limit: int = DEFAULT_LIMIT) -> CollectionResult:
        self._validate(source, limit)
        captured_at = self._now()

        items: list[RawItem] = []
        failures: list[ItemFailure] = []

        # Access errors raised by the fetcher propagate so a blocked run stops
        # cleanly. Only per-item mapping errors are isolated here.
        for post in self._fetch_posts(source.username or "", limit):
            try:
                items.append(map_post_to_raw_item(post, source, captured_at))
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
    """Reads recent public posts through Instaloader without downloading media."""

    def __init__(self, *, request_timeout: float = 30.0, max_connection_attempts: int = 2) -> None:
        self._request_timeout = request_timeout
        self._max_connection_attempts = max_connection_attempts

    def _build_loader(self) -> Any:
        import instaloader

        return instaloader.Instaloader(
            quiet=True,
            sleep=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            iphone_support=False,
            max_connection_attempts=self._max_connection_attempts,
            request_timeout=self._request_timeout,
        )

    def __call__(self, username: str, limit: int) -> Iterator[Any]:
        import instaloader
        from instaloader import exceptions as instaloader_errors

        loader = self._build_loader()
        try:
            profile = instaloader.Profile.from_username(loader.context, username)
            if profile.is_private:
                raise SourceAccessRestrictedError(
                    f"Instagram profile @{username} is private; "
                    "GatherRadar collects public content only"
                )
            for index, post in enumerate(profile.get_posts()):
                if index >= limit:
                    break
                yield post
        except instaloader_errors.InstaloaderException as exc:
            raise _translate_instaloader_error(username, exc) from exc


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
        return SourceAccessRestrictedError(
            f"Instagram rate-limited this run and refused the request; wait before retrying: {exc}"
        )
    if isinstance(exc, (errors.LoginRequiredException, errors.QueryReturnedForbiddenException)):
        return SourceAccessRestrictedError(
            "Instagram refused anonymous access and asked for a logged-in session"
        )
    if isinstance(exc, errors.ConnectionException):
        return SourceUnavailableError(f"Could not reach Instagram: {exc}")
    return SourceUnavailableError(f"Instagram collection failed: {type(exc).__name__}: {exc}")
