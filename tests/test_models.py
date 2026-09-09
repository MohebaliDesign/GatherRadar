import unittest
from datetime import datetime

from gatherradar.domain import EventCandidate, RawItem, Source, SourceType


class ModelTests(unittest.TestCase):
    def test_instagram_source_requires_username(self) -> None:
        with self.assertRaises(ValueError):
            Source(
                id="instagram_missing_username",
                publisher_key="example",
                name="Example Instagram",
                source_type=SourceType.INSTAGRAM,
                url="https://www.instagram.com/example/",
            )

    def test_raw_item_requires_timezone_aware_capture_time(self) -> None:
        with self.assertRaises(ValueError):
            RawItem(
                id="raw_1",
                source_id="source_1",
                source_type=SourceType.WEBSITE,
                external_id="external_1",
                content_type="event_page",
                content_url="https://example.com/event/1",
                raw_text="sample",
                captured_at=datetime(2026, 9, 9, 12, 0),
            )

    def test_candidate_confidence_must_be_between_zero_and_one(self) -> None:
        with self.assertRaises(ValueError):
            EventCandidate(
                candidate_id="candidate_1",
                raw_item_id="raw_1",
                is_event=True,
                extraction_confidence=1.2,
            )


if __name__ == "__main__":
    unittest.main()
