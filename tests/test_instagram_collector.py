import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from gatherradar.collectors.base import (
    AuthenticationRequiredError,
    SourceAccessRestrictedError,
    SourceConfigurationError,
    SourceDisabledError,
    SourceTypeMismatchError,
    SourceUnavailableError,
)
from gatherradar.collectors.instagram import (
    COLLECTOR_VERSION,
    ORIGIN_POST,
    ORIGIN_REEL,
    InstagramCollector,
    InstaloaderPostFetcher,
    build_raw_item_id,
    content_type_for,
    map_post_to_raw_item,
)
from gatherradar.collectors.instagram_auth import SessionInvalidError, SessionNotFoundError
from gatherradar.domain import Source, SourceType


CAPTURED_AT = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def make_source(**overrides):
    values = {
        "id": "davvvat_instagram",
        "publisher_key": "davvvat",
        "name": "Davvvat Instagram",
        "source_type": SourceType.INSTAGRAM,
        "url": "https://www.instagram.com/davvvat/",
        "username": "davvvat",
    }
    values.update(overrides)
    return Source(**values)


def make_post(**overrides):
    """A stand-in for an Instaloader Post, matching the attributes the adapter reads."""
    values = {
        "shortcode": "ABC123",
        "mediaid": 17998877665544332,
        "typename": "GraphImage",
        "is_video": False,
        "caption": "کارگاه طراحی شهری، جمعه ساعت ۱۷ #رویداد",
        "caption_hashtags": ["رویداد"],
        "caption_mentions": [],
        "date_utc": datetime(2026, 9, 9, 14, 30),
        "owner_username": "davvvat",
        "url": "https://scontent.example.com/image.jpg",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ContentTypeTests(unittest.TestCase):
    def test_typenames_map_to_content_types(self) -> None:
        self.assertEqual(content_type_for("GraphImage"), "image")
        self.assertEqual(content_type_for("GraphSidecar"), "carousel")

    def test_plain_video_post_maps_to_video(self) -> None:
        # The anonymous web timeline exposes no clips marker on a regular post, so a
        # video post stays "video" unless it was fetched through get_reels().
        self.assertEqual(content_type_for("GraphVideo"), "video")

    def test_reel_origin_is_labeled_reel_regardless_of_typename(self) -> None:
        self.assertEqual(content_type_for("GraphVideo", origin=ORIGIN_REEL), "reel")
        self.assertEqual(content_type_for(None, origin=ORIGIN_REEL), "reel")

    def test_unrecognized_typename_is_unknown(self) -> None:
        self.assertEqual(content_type_for("GraphSomethingNew"), "unknown")
        self.assertEqual(content_type_for(None), "unknown")


class StableIdTests(unittest.TestCase):
    def test_id_combines_source_identity_and_shortcode(self) -> None:
        self.assertEqual(build_raw_item_id("davvvat", "ABC123"), "instagram:davvvat:ABC123")

    def test_id_is_case_insensitive_for_username(self) -> None:
        self.assertEqual(build_raw_item_id("DavVVat", "ABC123"), "instagram:davvvat:ABC123")

    def test_same_post_yields_same_id_across_runs(self) -> None:
        source = make_source()
        first = map_post_to_raw_item(make_post(), source, CAPTURED_AT)
        later = map_post_to_raw_item(
            make_post(), source, datetime(2027, 1, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(first.id, later.id)


class MappingTests(unittest.TestCase):
    def test_post_maps_onto_raw_item_contract(self) -> None:
        item = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)

        self.assertEqual(item.id, "instagram:davvvat:ABC123")
        self.assertEqual(item.source_id, "davvvat_instagram")
        self.assertIs(item.source_type, SourceType.INSTAGRAM)
        self.assertEqual(item.external_id, "ABC123")
        self.assertEqual(item.content_type, "image")
        self.assertEqual(item.content_url, "https://www.instagram.com/p/ABC123/")
        self.assertEqual(item.author, "davvvat")
        self.assertEqual(item.image_url, "https://scontent.example.com/image.jpg")

    def test_reel_origin_is_labeled_and_recorded_in_metadata(self) -> None:
        item = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT, origin=ORIGIN_REEL)

        self.assertEqual(item.content_type, "reel")
        self.assertEqual(item.raw_metadata["origin"], ORIGIN_REEL)

    def test_post_origin_is_recorded_in_metadata(self) -> None:
        item = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        self.assertEqual(item.raw_metadata["origin"], ORIGIN_POST)

    def test_caption_is_preserved_verbatim(self) -> None:
        caption = "رویداد ویژه\nجمعه ۱۹ مهر ساعت ۱۷:۳۰"
        item = map_post_to_raw_item(make_post(caption=caption), make_source(), CAPTURED_AT)
        self.assertEqual(item.raw_text, caption)

    def test_missing_caption_becomes_empty_text(self) -> None:
        item = map_post_to_raw_item(make_post(caption=None), make_source(), CAPTURED_AT)
        self.assertEqual(item.raw_text, "")

    def test_naive_instaloader_timestamp_becomes_utc_aware(self) -> None:
        item = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        self.assertIsNotNone(item.published_at)
        self.assertEqual(item.published_at.utcoffset().total_seconds(), 0)
        self.assertEqual(item.published_at.isoformat(), "2026-09-09T14:30:00+00:00")

    def test_aware_timestamp_is_converted_not_relabelled(self) -> None:
        tehran_noon = datetime.fromisoformat("2026-09-09T12:00:00+03:30")
        item = map_post_to_raw_item(
            make_post(date_utc=tehran_noon), make_source(), CAPTURED_AT
        )
        self.assertEqual(item.published_at.isoformat(), "2026-09-09T08:30:00+00:00")

    def test_missing_publish_date_is_null(self) -> None:
        item = map_post_to_raw_item(make_post(date_utc=None), make_source(), CAPTURED_AT)
        self.assertIsNone(item.published_at)

    def test_adapter_details_stay_in_raw_metadata(self) -> None:
        post = make_post(typename="GraphVideo", is_video=True, caption_mentions=["venue"])
        item = map_post_to_raw_item(post, make_source(), CAPTURED_AT)

        self.assertEqual(item.raw_metadata["collector_version"], COLLECTOR_VERSION)
        self.assertEqual(item.raw_metadata["typename"], "GraphVideo")
        self.assertEqual(item.raw_metadata["media_id"], "17998877665544332")
        self.assertTrue(item.raw_metadata["is_video"])
        self.assertEqual(item.raw_metadata["mentions"], ["venue"])

    def test_post_without_shortcode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            map_post_to_raw_item(make_post(shortcode=None), make_source(), CAPTURED_AT)

    def test_owner_falls_back_to_configured_username(self) -> None:
        class NoOwner(SimpleNamespace):
            @property
            def owner_username(self):
                raise KeyError("owner")

        post = NoOwner(**vars(make_post()))
        item = map_post_to_raw_item(post, make_source(), CAPTURED_AT)
        self.assertEqual(item.author, "davvvat")


class ContentHashTests(unittest.TestCase):
    def test_same_post_content_yields_same_hash(self) -> None:
        first = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        later = map_post_to_raw_item(
            make_post(), make_source(), datetime(2027, 1, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(first.content_hash, later.content_hash)

    def test_captured_at_does_not_affect_the_hash(self) -> None:
        a = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        b = map_post_to_raw_item(
            make_post(), make_source(), datetime(2030, 5, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(a.content_hash, b.content_hash)

    def test_edited_caption_changes_the_hash(self) -> None:
        original = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        edited = map_post_to_raw_item(
            make_post(caption="رویداد لغو شد"), make_source(), CAPTURED_AT
        )
        self.assertNotEqual(original.content_hash, edited.content_hash)

    def test_persian_caption_change_is_detected(self) -> None:
        a = map_post_to_raw_item(
            make_post(caption="جمعه ساعت ۱۷"), make_source(), CAPTURED_AT
        )
        b = map_post_to_raw_item(
            make_post(caption="جمعه ساعت ۱۸"), make_source(), CAPTURED_AT
        )
        self.assertNotEqual(a.content_hash, b.content_hash)

    def test_empty_caption_still_produces_a_stable_hash(self) -> None:
        a = map_post_to_raw_item(make_post(caption=""), make_source(), CAPTURED_AT)
        b = map_post_to_raw_item(make_post(caption=""), make_source(), CAPTURED_AT)
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertTrue(a.content_hash)

    def test_hash_is_deterministic_sha256_hex_digest(self) -> None:
        item = map_post_to_raw_item(make_post(), make_source(), CAPTURED_AT)
        self.assertEqual(len(item.content_hash), 64)
        int(item.content_hash, 16)  # raises ValueError if not hex


class CollectorTests(unittest.TestCase):
    def test_collects_and_maps_posts(self) -> None:
        posts = [make_post(shortcode="A1"), make_post(shortcode="B2")]
        collector = InstagramCollector(
            fetch_posts=lambda username, limit: [(ORIGIN_POST, p) for p in posts[:limit]],
            now=lambda: CAPTURED_AT,
        )

        result = collector.collect(make_source(), limit=5)

        self.assertEqual(result.observed, 2)
        self.assertEqual([item.external_id for item in result.items], ["A1", "B2"])
        self.assertEqual(result.failures, ())

    def test_limit_is_passed_to_the_fetcher(self) -> None:
        seen = {}

        def fetch(username, limit):
            seen["username"] = username
            seen["limit"] = limit
            return []

        InstagramCollector(fetch_posts=fetch, now=lambda: CAPTURED_AT).collect(
            make_source(), limit=3
        )
        self.assertEqual(seen, {"username": "davvvat", "limit": 3})

    def test_one_malformed_post_does_not_discard_the_others(self) -> None:
        posts = [
            (ORIGIN_POST, make_post(shortcode="A1")),
            (ORIGIN_POST, make_post(shortcode=None)),
            (ORIGIN_POST, make_post(shortcode="C3")),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda username, limit: posts,
            now=lambda: CAPTURED_AT,
        )

        result = collector.collect(make_source(), limit=5)

        self.assertEqual([item.external_id for item in result.items], ["A1", "C3"])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.observed, 3)

    def test_website_source_is_refused(self) -> None:
        website = Source(
            id="davvvat_website",
            publisher_key="davvvat",
            name="Davvvat Website",
            source_type=SourceType.WEBSITE,
            url="https://davvvat.ir/",
        )
        with self.assertRaises(SourceTypeMismatchError):
            InstagramCollector(fetch_posts=lambda u, l: []).collect(website, limit=5)

    def test_disabled_source_is_refused(self) -> None:
        with self.assertRaises(SourceDisabledError):
            InstagramCollector(fetch_posts=lambda u, l: []).collect(
                make_source(enabled=False), limit=5
            )

    def test_source_without_username_is_refused(self) -> None:
        source = make_source()
        # Source itself blocks this, so bypass its guard to reach the collector's.
        object.__setattr__(source, "username", "   ")
        with self.assertRaises(SourceConfigurationError):
            InstagramCollector(fetch_posts=lambda u, l: []).collect(source, limit=5)

    def test_limit_must_be_positive(self) -> None:
        collector = InstagramCollector(fetch_posts=lambda u, l: [])
        with self.assertRaises(ValueError):
            collector.collect(make_source(), limit=0)


class PostsAndReelsTests(unittest.TestCase):
    """Covers combining Instagram's posts and reels feeds into one bounded sequence."""

    def test_reel_content_type_is_classified_from_origin(self) -> None:
        candidates = [(ORIGIN_REEL, make_post(shortcode="R1", typename="GraphVideo"))]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=5)

        self.assertEqual(result.items[0].content_type, "reel")

    def test_posts_and_reels_are_combined_into_one_sequence(self) -> None:
        candidates = [
            (ORIGIN_POST, make_post(shortcode="P1", date_utc=datetime(2026, 9, 9, 10, 0))),
            (ORIGIN_REEL, make_post(shortcode="R1", date_utc=datetime(2026, 9, 9, 11, 0))),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=5)

        self.assertEqual(
            {item.external_id for item in result.items}, {"P1", "R1"}
        )

    def test_same_shortcode_in_posts_and_reels_is_returned_once(self) -> None:
        candidates = [
            (ORIGIN_POST, make_post(shortcode="DUP", date_utc=datetime(2026, 9, 9, 10, 0))),
            (ORIGIN_REEL, make_post(shortcode="DUP", date_utc=datetime(2026, 9, 9, 10, 0))),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=5)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.observed, 1)

    def test_combined_result_is_bounded_by_limit(self) -> None:
        candidates = [
            (ORIGIN_POST, make_post(shortcode="P1")),
            (ORIGIN_POST, make_post(shortcode="P2")),
            (ORIGIN_REEL, make_post(shortcode="R1")),
            (ORIGIN_REEL, make_post(shortcode="R2")),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=2)

        self.assertEqual(result.observed, 2)

    def test_most_recent_items_are_preferred_when_bounded(self) -> None:
        candidates = [
            (ORIGIN_POST, make_post(shortcode="OLD", date_utc=datetime(2026, 1, 1))),
            (ORIGIN_REEL, make_post(shortcode="NEW", date_utc=datetime(2026, 9, 9))),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=1)

        self.assertEqual(result.items[0].external_id, "NEW")

    def test_items_without_timestamps_sort_after_timestamped_ones(self) -> None:
        candidates = [
            (ORIGIN_POST, make_post(shortcode="NO_DATE", date_utc=None)),
            (ORIGIN_REEL, make_post(shortcode="DATED", date_utc=datetime(2026, 1, 1))),
        ]
        collector = InstagramCollector(
            fetch_posts=lambda u, l: candidates, now=lambda: CAPTURED_AT
        )

        result = collector.collect(make_source(), limit=2)

        self.assertEqual(
            [item.external_id for item in result.items], ["DATED", "NO_DATE"]
        )


class ErrorTranslationTests(unittest.TestCase):
    """Instaloader failures must surface as GatherRadar errors, never library types."""

    def setUp(self) -> None:
        from instaloader import exceptions

        self.errors = exceptions

    def translate(self, exc):
        from gatherradar.collectors.instagram import _translate_instaloader_error

        return _translate_instaloader_error("davvvat", exc)

    def test_missing_profile_is_unavailable(self) -> None:
        result = self.translate(self.errors.ProfileNotExistsException("gone"))
        self.assertIsInstance(result, SourceUnavailableError)
        self.assertNotIsInstance(result, SourceAccessRestrictedError)
        self.assertIn("davvvat", str(result))

    def test_private_profile_is_access_restricted(self) -> None:
        result = self.translate(self.errors.PrivateProfileNotFollowedException("private"))
        self.assertIsInstance(result, SourceAccessRestrictedError)

    def test_login_requirement_is_access_restricted(self) -> None:
        result = self.translate(self.errors.LoginRequiredException("login"))
        self.assertIsInstance(result, SourceAccessRestrictedError)

    def test_rate_limit_survives_being_rewrapped_as_a_connection_error(self) -> None:
        # What a real blocked run raises once Instaloader has exhausted its retries.
        exhausted = self.errors.ConnectionException(
            "JSON Query to api/v1/users/web_profile_info/: 429 Too Many Requests"
        )
        result = self.translate(exhausted)

        self.assertIsInstance(result, SourceAccessRestrictedError)
        self.assertIn("429", str(result))

    def test_rate_limit_message_does_not_overclaim_an_ip_block(self) -> None:
        result = self.translate(self.errors.TooManyRequestsException("429 Too Many Requests"))
        message = str(result).lower()
        self.assertNotIn("ip", message)
        self.assertNotIn("blocked", message)

    def test_plain_network_failure_stays_unavailable(self) -> None:
        result = self.translate(self.errors.ConnectionException("connection reset"))
        self.assertIsInstance(result, SourceUnavailableError)
        self.assertNotIsInstance(result, SourceAccessRestrictedError)


class FetcherConfigurationTests(unittest.TestCase):
    """A blocked run should fail fast rather than trigger Instaloader's long backoff."""

    def test_default_max_connection_attempts_is_one(self) -> None:
        fetcher = InstaloaderPostFetcher()
        self.assertEqual(fetcher._max_connection_attempts, 1)


class FetcherAuthenticationTests(unittest.TestCase):
    """The real fetcher must use an authenticated session and never silently fall
    back to anonymous requests, which are known to be blocked (HTTP 429)."""

    def test_missing_session_reports_authentication_not_configured(self) -> None:
        def load_session(username):
            raise SessionNotFoundError("no session file")

        fetcher = InstaloaderPostFetcher(load_session=load_session)

        with self.assertRaises(AuthenticationRequiredError) as ctx:
            list(fetcher("davvvat", 5))
        self.assertIn("auth instagram davvvat", str(ctx.exception))

    def test_invalid_session_reports_authentication_required_not_anonymous_fallback(
        self,
    ) -> None:
        def load_session(username):
            raise SessionInvalidError("session expired")

        fetcher = InstaloaderPostFetcher(load_session=load_session)

        with self.assertRaises(AuthenticationRequiredError) as ctx:
            list(fetcher("davvvat", 5))
        self.assertIn("no longer valid", str(ctx.exception))

    def test_valid_injected_session_is_used_to_fetch_posts(self) -> None:
        fake_loader = SimpleNamespace(context=SimpleNamespace())
        fake_profile = SimpleNamespace(
            is_private=False,
            get_posts=lambda: iter([make_post(shortcode="A1")]),
            get_reels=lambda: iter([]),
        )

        fetcher = InstaloaderPostFetcher(load_session=lambda username: fake_loader)

        with mock.patch(
            "instaloader.Profile.from_username", return_value=fake_profile
        ) as from_username:
            results = list(fetcher("davvvat", 5))

        from_username.assert_called_once_with(fake_loader.context, "davvvat")
        self.assertEqual([post.shortcode for _origin, post in results], ["A1"])


class CollectorDataDirWiringTests(unittest.TestCase):
    """InstagramCollector must pass its data_dir through to the default fetcher so
    it looks for sessions under the same root the CLI's --data-dir points at."""

    def test_default_fetcher_uses_the_requested_data_dir(self) -> None:
        collector = InstagramCollector(data_dir="custom-data")
        self.assertIsInstance(collector._fetch_posts, InstaloaderPostFetcher)
        self.assertEqual(collector._fetch_posts._data_dir, "custom-data")

    def test_injected_fetch_posts_bypasses_data_dir(self) -> None:
        sentinel = lambda username, limit: []
        collector = InstagramCollector(fetch_posts=sentinel, data_dir="custom-data")
        self.assertIs(collector._fetch_posts, sentinel)


if __name__ == "__main__":
    unittest.main()
