import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from gatherradar.config import load_sources
from gatherradar.domain import SourceType


ROOT = Path(__file__).resolve().parents[1]


class SourceConfigTests(unittest.TestCase):
    def test_initial_registry_loads_all_sources(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        self.assertEqual(len(sources), 8)
        self.assertEqual(len({source.id for source in sources}), 8)

    def test_instagram_urls_are_canonical_and_have_usernames(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        instagram_sources = [s for s in sources if s.source_type is SourceType.INSTAGRAM]
        self.assertEqual(len(instagram_sources), 5)
        for source in instagram_sources:
            self.assertIsNotNone(source.username)
            self.assertNotIn("igsi", source.url)
            self.assertFalse(urlparse(source.url).query)

    def test_tracking_parameters_are_not_committed(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        for source in sources:
            query = parse_qs(urlparse(source.url).query)
            self.assertNotIn("utm_source", query)
            self.assertNotIn("utm_medium", query)
            self.assertNotIn("fbclid", query)


if __name__ == "__main__":
    unittest.main()
