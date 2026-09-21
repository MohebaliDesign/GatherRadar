import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.collectors.instagram_evidence import (
    capture_post_artifacts, capture_reel_artifacts, sample_reel_timestamps,
)
from gatherradar.domain import MediaKind, RawItem, SourceType
from gatherradar.storage import MediaArtifactStore


def raw_item(content_type='image'):
    return RawItem(
        id='instagram:source:ABC', source_id='source',
        source_type=SourceType.INSTAGRAM, external_id='ABC',
        content_type=content_type, content_url='https://www.instagram.com/p/ABC/',
        raw_text='', captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        content_hash='a' * 64,
    )


class FakeDriver:
    def __init__(self, visuals=(), duration=5000, fail_at=()):
        self.visuals = list(visuals)
        self.index = 0
        self.duration = duration
        self.fail_at = set(fail_at)
        self.frame_calls = []

    def capture_current_visual(self):
        if self.index in self.fail_at:
            raise ValueError('broken slide')
        return self.visuals[self.index]

    def advance_carousel(self):
        if self.index + 1 >= len(self.visuals):
            return False
        self.index += 1
        return True

    def video_duration_ms(self):
        return self.duration

    def capture_frame(self, timestamp):
        self.frame_calls.append(timestamp)
        if timestamp in self.fail_at:
            raise ValueError('broken frame')
        return self.visuals[timestamp % len(self.visuals)]


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_paths_are_deterministic_and_below_data_root(self):
        first = self.store.write(raw_item(), MediaKind.IMAGE, b'image')
        second = self.store.write(raw_item(), MediaKind.IMAGE, b'image')
        self.assertEqual(first.artifact.local_path, second.artifact.local_path)
        self.assertTrue(first.artifact.local_path.is_relative_to(Path(self.temp.name)))
        self.assertTrue(first.created)
        self.assertFalse(second.created)

    def test_hash_is_sha256_and_part_of_identity(self):
        one = self.store.write(raw_item(), MediaKind.IMAGE, b'one').artifact
        two = self.store.write(raw_item(), MediaKind.IMAGE, b'two').artifact
        self.assertEqual(len(one.asset_hash), 64)
        self.assertNotEqual(one.artifact_id, two.artifact_id)
        self.assertNotEqual(one.local_path, two.local_path)

    def test_position_is_part_of_carousel_path_and_identity(self):
        one = self.store.write(
            raw_item(), MediaKind.CAROUSEL_SLIDE, b'same', slide_index=0
        ).artifact
        two = self.store.write(
            raw_item(), MediaKind.CAROUSEL_SLIDE, b'same', slide_index=1
        ).artifact
        self.assertNotEqual(one.artifact_id, two.artifact_id)
        self.assertIn('slide-000', one.local_path.name)


class CarouselCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_one_visual_is_an_image(self):
        result = capture_post_artifacts(FakeDriver([b'one']), raw_item(), self.store)
        self.assertEqual([item.kind for item in result.artifacts], [MediaKind.IMAGE])

    def test_carousel_preserves_slide_order(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three']), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0, 1, 2])

    def test_maximum_slide_bound_is_enforced(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three']), raw_item(), self.store,
            max_slides=2,
        )
        self.assertEqual(len(result.artifacts), 2)

    def test_duplicate_visual_stops_the_carousel(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'two', b'three']), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0, 1])

    def test_one_slide_failure_is_isolated(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three'], fail_at={1}), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0, 2])
        self.assertEqual(len(result.failures), 1)


class ReelCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_timestamps_are_deterministic_and_bounded(self):
        timestamps = sample_reel_timestamps(10_000, 4)
        self.assertEqual(timestamps, sample_reel_timestamps(10_000, 4))
        self.assertEqual(len(timestamps), 4)
        self.assertEqual(timestamps[0], 0)
        self.assertLess(timestamps[-1], 10_000)

    def test_missing_video_duration_is_reported(self):
        result = capture_reel_artifacts(
            FakeDriver([b'frame'], duration=None), raw_item('reel'), self.store
        )
        self.assertEqual(result.artifacts, ())
        self.assertIn('duration', result.failures[0].reason)

    def test_duplicate_frames_are_skipped(self):
        driver = FakeDriver([b'same'], duration=5000)
        result = capture_reel_artifacts(driver, raw_item('reel'), self.store, max_frames=4)
        self.assertEqual(len(result.artifacts), 1)
        self.assertLessEqual(len(driver.frame_calls), 4)

    def test_one_frame_failure_does_not_discard_other_frames(self):
        timestamps = sample_reel_timestamps(5000, 3)
        driver = FakeDriver([b'a', b'b', b'c'], duration=5000, fail_at={timestamps[1]})
        result = capture_reel_artifacts(driver, raw_item('reel'), self.store, max_frames=3)
        self.assertGreaterEqual(len(result.artifacts), 1)
        self.assertEqual(len(result.failures), 1)


if __name__ == '__main__':
    unittest.main()
