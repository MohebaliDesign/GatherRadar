from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain import MediaArtifact, MediaKind, RawItem, Source, SourceType
from ..storage.media import MediaArtifactStore
from .base import SourceDisabledError, SourceTypeMismatchError
from .instagram_browser import (
    BrowserSessionExpiredError,
    PlaywrightChromeLauncher,
    SESSION_EXPIRED_MESSAGE,
    _ensure_location_allowed,
    _goto,
    _wait_for_optional,
    browser_profile_path,
    has_instagram_session_cookie,
    open_authenticated_browser,
)

DEFAULT_MAX_CAROUSEL_SLIDES = 20
DEFAULT_MAX_REEL_FRAMES = 6


class MediaPageDriver(Protocol):
    def capture_current_visual(self) -> bytes: ...
    def advance_carousel(self) -> bool: ...
    def video_duration_ms(self) -> int | None: ...
    def capture_frame(self, timestamp_ms: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MediaCaptureFailure:
    raw_item_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class MediaCaptureResult:
    artifacts: tuple[MediaArtifact, ...] = ()
    failures: tuple[MediaCaptureFailure, ...] = ()

    @property
    def images(self) -> int:
        return sum(item.kind is MediaKind.IMAGE for item in self.artifacts)

    @property
    def carousel_slides(self) -> int:
        return sum(item.kind is MediaKind.CAROUSEL_SLIDE for item in self.artifacts)

    @property
    def reel_frames(self) -> int:
        return sum(item.kind is MediaKind.REEL_FRAME for item in self.artifacts)


def sample_reel_timestamps(duration_ms: int | None, max_frames: int) -> tuple[int, ...]:
    if isinstance(max_frames, bool) or max_frames < 1:
        raise ValueError('max_frames must be positive')
    if duration_ms is None or duration_ms <= 0:
        return ()
    count = min(max_frames, max(1, duration_ms // 1000 + 1))
    if count == 1:
        return (0,)
    final = max(0, duration_ms - 100)
    return tuple(dict.fromkeys(round(index * final / (count - 1)) for index in range(count)))


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def capture_post_artifacts(
    driver: MediaPageDriver, raw_item: RawItem, store: MediaArtifactStore, *,
    max_slides: int = DEFAULT_MAX_CAROUSEL_SLIDES,
) -> MediaCaptureResult:
    if max_slides < 1:
        raise ValueError('max_slides must be positive')
    failures: list[MediaCaptureFailure] = []
    try:
        first = driver.capture_current_visual()
    except Exception as exc:
        return MediaCaptureResult(
            failures=(MediaCaptureFailure(raw_item.id, f'visual capture failed: {exc}'),)
        )
    try:
        has_next = driver.advance_carousel()
    except Exception as exc:
        failures.append(MediaCaptureFailure(raw_item.id, f'carousel advance failed: {exc}'))
        has_next = False
    if not has_next:
        outcome = store.write(raw_item, MediaKind.IMAGE, first)
        return MediaCaptureResult((outcome.artifact,), tuple(failures))

    artifacts: list[MediaArtifact] = [
        store.write(raw_item, MediaKind.CAROUSEL_SLIDE, first, slide_index=0).artifact
    ]
    hashes = {_hash(first)}
    index = 1
    while index < max_slides:
        try:
            content = driver.capture_current_visual()
            digest = _hash(content)
            if digest in hashes:
                break
            hashes.add(digest)
            artifacts.append(
                store.write(
                    raw_item, MediaKind.CAROUSEL_SLIDE, content, slide_index=index
                ).artifact
            )
        except Exception as exc:
            failures.append(MediaCaptureFailure(raw_item.id, f'slide {index} failed: {exc}'))
        index += 1
        try:
            if not driver.advance_carousel():
                break
        except Exception as exc:
            failures.append(MediaCaptureFailure(raw_item.id, f'carousel advance failed: {exc}'))
            break
    return MediaCaptureResult(tuple(artifacts), tuple(failures))


def capture_reel_artifacts(
    driver: MediaPageDriver, raw_item: RawItem, store: MediaArtifactStore, *,
    max_frames: int = DEFAULT_MAX_REEL_FRAMES,
) -> MediaCaptureResult:
    try:
        timestamps = sample_reel_timestamps(driver.video_duration_ms(), max_frames)
    except Exception as exc:
        return MediaCaptureResult(
            failures=(MediaCaptureFailure(raw_item.id, f'video inspection failed: {exc}'),)
        )
    if not timestamps:
        return MediaCaptureResult(
            failures=(MediaCaptureFailure(raw_item.id, 'video duration is unavailable'),)
        )
    artifacts: list[MediaArtifact] = []
    failures: list[MediaCaptureFailure] = []
    hashes: set[str] = set()
    for timestamp in timestamps:
        try:
            content = driver.capture_frame(timestamp)
            digest = _hash(content)
            if digest in hashes:
                continue
            hashes.add(digest)
            artifacts.append(
                store.write(
                    raw_item, MediaKind.REEL_FRAME, content,
                    frame_timestamp_ms=timestamp,
                ).artifact
            )
        except Exception as exc:
            failures.append(
                MediaCaptureFailure(raw_item.id, f'frame {timestamp} ms failed: {exc}')
            )
    return MediaCaptureResult(tuple(artifacts), tuple(failures))


class PlaywrightMediaPageDriver:
    '''Small browser-specific layer around the bounded capture algorithms.'''

    def __init__(self, page: Any, *, settle_ms: int = 500) -> None:
        self.page = page
        self.settle_ms = settle_ms

    def _largest_visible(self, selector: str) -> Any:
        locator = self.page.locator(selector)
        choices: list[tuple[float, Any]] = []
        for index in range(locator.count()):
            item = locator.nth(index)
            if not item.is_visible():
                continue
            box = item.bounding_box() or {}
            choices.append((float(box.get('width', 0)) * float(box.get('height', 0)), item))
        if not choices:
            raise ValueError('no displayed media element was found')
        return max(choices, key=lambda entry: entry[0])[1]

    def capture_current_visual(self) -> bytes:
        return self._largest_visible('article img').screenshot(type='png')

    def advance_carousel(self) -> bool:
        selector = (
            'article button[aria-label=Next], '
            'article button[aria-label=بعدی], '
            'article button:has(svg[aria-label=Next])'
        )
        controls = self.page.locator(selector)
        for index in range(controls.count() - 1, -1, -1):
            control = controls.nth(index)
            if control.is_visible() and control.is_enabled():
                control.click()
                self.page.wait_for_timeout(self.settle_ms)
                return True
        return False

    def _video(self) -> Any:
        return self._largest_visible('article video, main video')

    def video_duration_ms(self) -> int | None:
        duration = self._video().evaluate('(video) => video.duration')
        if not isinstance(duration, (int, float)) or duration <= 0:
            return None
        return round(duration * 1000)

    def capture_frame(self, timestamp_ms: int) -> bytes:
        video = self._video()
        video.evaluate(
            '''(video, seconds) => new Promise((resolve) => {
                const done = () => resolve();
                video.addEventListener('seeked', done, {once: true});
                video.currentTime = Math.min(seconds, Math.max(0, video.duration - 0.05));
                setTimeout(done, 1500);
            })''',
            timestamp_ms / 1000,
        )
        return video.screenshot(type='png')


class InstagramMediaEvidenceAcquirer:
    def __init__(
        self, *, data_dir: str | Path = 'data', launcher: Any | None = None,
        navigation_timeout_ms: int = 30_000,
        content_wait_ms: int = 10_000,
        max_carousel_slides: int = DEFAULT_MAX_CAROUSEL_SLIDES,
        max_reel_frames: int = DEFAULT_MAX_REEL_FRAMES,
    ) -> None:
        self.profile_dir = browser_profile_path(data_dir)
        self.launcher = launcher
        self.navigation_timeout_ms = navigation_timeout_ms
        self.content_wait_ms = content_wait_ms
        self.max_carousel_slides = max_carousel_slides
        self.max_reel_frames = max_reel_frames

    def acquire(
        self, raw_items: tuple[RawItem, ...], source: Source,
        store: MediaArtifactStore,
    ) -> MediaCaptureResult:
        if source.source_type is not SourceType.INSTAGRAM:
            raise SourceTypeMismatchError(f'source {source.id} is not an Instagram source')
        if not source.enabled:
            raise SourceDisabledError(f'source {source.id} is disabled in the registry')
        launcher = self.launcher or PlaywrightChromeLauncher(
            timeout_ms=self.navigation_timeout_ms
        )
        artifacts: list[MediaArtifact] = []
        failures: list[MediaCaptureFailure] = []
        with open_authenticated_browser(self.profile_dir.resolve(), launcher) as browser:
            for raw_item in raw_items:
                try:
                    _goto(browser.page, raw_item.content_url, self.navigation_timeout_ms)
                    _ensure_location_allowed(browser.page.url)
                    if not has_instagram_session_cookie(browser.context):
                        raise BrowserSessionExpiredError(SESSION_EXPIRED_MESSAGE)
                    _wait_for_optional(
                        browser.page, 'article img, article video, main video',
                        self.content_wait_ms,
                    )
                    driver = PlaywrightMediaPageDriver(browser.page)
                    if raw_item.content_type == 'reel':
                        result = capture_reel_artifacts(
                            driver, raw_item, store, max_frames=self.max_reel_frames
                        )
                    else:
                        result = capture_post_artifacts(
                            driver, raw_item, store, max_slides=self.max_carousel_slides
                        )
                    artifacts.extend(result.artifacts)
                    failures.extend(result.failures)
                except BrowserSessionExpiredError:
                    raise
                except Exception as exc:
                    failures.append(
                        MediaCaptureFailure(raw_item.id, f'media page failed: {exc}')
                    )
        return MediaCaptureResult(tuple(artifacts), tuple(failures))


__all__ = [
    'DEFAULT_MAX_CAROUSEL_SLIDES', 'DEFAULT_MAX_REEL_FRAMES',
    'InstagramMediaEvidenceAcquirer', 'MediaCaptureFailure', 'MediaCaptureResult',
    'MediaPageDriver', 'PlaywrightMediaPageDriver', 'capture_post_artifacts',
    'capture_reel_artifacts', 'sample_reel_timestamps',
]
