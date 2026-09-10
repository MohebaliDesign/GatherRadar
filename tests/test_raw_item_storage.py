import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.domain import RawItem, SourceType
from gatherradar.storage.jsonl import JsonlRawItemStore, StorageError, raw_item_to_dict


CAPTURED_AT = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def make_item(shortcode: str = "ABC123", **overrides) -> RawItem:
    values = {
        "id": f"instagram:davvvat:{shortcode}",
        "source_id": "davvvat_instagram",
        "source_type": SourceType.INSTAGRAM,
        "external_id": shortcode,
        "content_type": "image",
        "content_url": f"https://www.instagram.com/p/{shortcode}/",
        "raw_text": "کارگاه طراحی شهری",
        "captured_at": CAPTURED_AT,
        "published_at": datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc),
        "author": "davvvat",
        "image_url": "https://scontent.example.com/image.jpg",
        "raw_metadata": {"typename": "GraphImage", "hashtags": []},
    }
    values.update(overrides)
    return RawItem(**values)


class SerializationTests(unittest.TestCase):
    def test_raw_item_serializes_to_contract_shape(self) -> None:
        payload = raw_item_to_dict(make_item())

        self.assertEqual(payload["id"], "instagram:davvvat:ABC123")
        self.assertEqual(payload["source_type"], "instagram")
        self.assertEqual(payload["captured_at"], "2026-09-10T09:00:00+00:00")
        self.assertEqual(payload["published_at"], "2026-09-09T14:30:00+00:00")
        self.assertEqual(payload["raw_metadata"]["typename"], "GraphImage")

    def test_missing_publish_date_serializes_as_null(self) -> None:
        payload = raw_item_to_dict(make_item(published_at=None))
        self.assertIsNone(payload["published_at"])

    def test_persian_text_is_not_escaped_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlRawItemStore(Path(tmp) / "davvvat.jsonl")
            store.append_new([make_item()])
            content = store.path.read_text(encoding="utf-8")

        self.assertIn("کارگاه طراحی شهری", content)


class JsonlStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "raw" / "instagram" / "davvvat.jsonl"
        self.store = JsonlRawItemStore(self.path)

    def test_first_write_creates_parent_directories(self) -> None:
        outcome = self.store.append_new([make_item("A1"), make_item("B2")])

        self.assertEqual(outcome.new, 2)
        self.assertEqual(outcome.already_existing, 0)
        self.assertTrue(self.path.exists())

    def test_each_line_is_one_complete_record(self) -> None:
        self.store.append_new([make_item("A1"), make_item("B2")])
        lines = self.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("source_id", json.loads(line))

    def test_rerunning_the_same_items_appends_nothing(self) -> None:
        items = [make_item("A1"), make_item("B2")]
        self.store.append_new(items)

        outcome = self.store.append_new(items)

        self.assertEqual(outcome.new, 0)
        self.assertEqual(outcome.already_existing, 2)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 2)

    def test_only_unseen_items_are_appended(self) -> None:
        self.store.append_new([make_item("A1")])

        outcome = self.store.append_new([make_item("A1"), make_item("B2")])

        self.assertEqual(outcome.new, 1)
        self.assertEqual(outcome.already_existing, 1)
        self.assertEqual(self.store.existing_ids(), {
            "instagram:davvvat:A1",
            "instagram:davvvat:B2",
        })

    def test_duplicates_inside_one_batch_are_written_once(self) -> None:
        outcome = self.store.append_new([make_item("A1"), make_item("A1")])

        self.assertEqual(outcome.new, 1)
        self.assertEqual(outcome.already_existing, 1)

    def test_existing_ids_is_empty_when_no_file_yet(self) -> None:
        self.assertEqual(self.store.existing_ids(), set())

    def test_corrupt_jsonl_is_reported_instead_of_duplicated(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json}\n", encoding="utf-8")

        with self.assertRaises(StorageError):
            self.store.existing_ids()

    def test_blank_lines_are_tolerated(self) -> None:
        self.store.append_new([make_item("A1")])
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n")

        self.assertEqual(self.store.existing_ids(), {"instagram:davvvat:A1"})


if __name__ == "__main__":
    unittest.main()
