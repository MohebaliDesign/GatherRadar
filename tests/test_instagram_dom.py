import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.collectors.instagram_dom import (
    ORIGIN_POST,
    ORIGIN_REEL,
    PROFILE_PRIVATE,
    PROFILE_UNAVAILABLE,
    PROFILE_UNKNOWN,
    MalformedMediaPageError,
    MediaLink,
    caption_hashtags,
    caption_mentions,
    detect_profile_state,
    discover_media_links,
    merge_media_links,
    parse_media_href,
    parse_media_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "instagram_browser"

POST1 = MediaLink("POST1", ORIGIN_POST, "https://www.instagram.com/p/POST1/")
REEL1 = MediaLink("REEL1", ORIGIN_REEL, "https://www.instagram.com/reel/REEL1/")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MediaHrefTests(unittest.TestCase):
    def test_post_link_forms_are_recognized(self) -> None:
        for href in (
            "/p/ABC_1-x/",
            "/davvvat/p/ABC_1-x/",
            "https://www.instagram.com/davvvat/p/ABC_1-x/",
            "https://instagram.com/p/ABC_1-x",
        ):
            with self.subTest(href=href):
                link = parse_media_href(href, "davvvat")
                self.assertEqual(
                    link, MediaLink("ABC_1-x", ORIGIN_POST, "https://www.instagram.com/p/ABC_1-x/")
                )

    def test_reel_link_is_recognized_as_reel(self) -> None:
        link = parse_media_href("/davvvat/reel/XYZ9/", "davvvat")
        self.assertEqual(link, MediaLink("XYZ9", ORIGIN_REEL, "https://www.instagram.com/reel/XYZ9/"))

    def test_owner_prefix_is_matched_case_insensitively(self) -> None:
        self.assertIsNotNone(parse_media_href("/DavVVat/p/ABC/", "davvvat"))

    def test_non_media_and_foreign_links_are_rejected(self) -> None:
        for href in (
            "/davvvat/p/ABC/c/17900000000000001/",
            "/explore/",
            "/davvvat/",
            "/someone_else/p/ABC/",
            "https://evil.example.test/p/ABC/",
            "javascript:alert(1)",
            "mailto:someone@example.test",
        ):
            with self.subTest(href=href):
                self.assertIsNone(parse_media_href(href, "davvvat"))


class DiscoverMediaLinksTests(unittest.TestCase):
    def test_profile_page_yields_posts_and_reels_in_page_order(self) -> None:
        links = discover_media_links(fixture("profile_davvvat.html"), "davvvat")

        self.assertEqual(
            [(link.shortcode, link.kind) for link in links],
            [("POST1", ORIGIN_POST), ("REEL1", ORIGIN_REEL), ("POST2", ORIGIN_POST), ("POST3", ORIGIN_POST)],
        )

    def test_same_shortcode_linked_as_post_and_reel_is_one_reel_link(self) -> None:
        html = '<a href="/davvvat/p/DUP/">a</a><a href="/davvvat/reel/DUP/">b</a>'
        links = discover_media_links(html, "davvvat")
        self.assertEqual(links, [MediaLink("DUP", ORIGIN_REEL, "https://www.instagram.com/reel/DUP/")])

    def test_merge_keeps_first_position_and_prefers_reel(self) -> None:
        first = MediaLink("X", ORIGIN_POST, "https://www.instagram.com/p/X/")
        reel = MediaLink("X", ORIGIN_REEL, "https://www.instagram.com/reel/X/")
        other = MediaLink("Y", ORIGIN_POST, "https://www.instagram.com/p/Y/")

        self.assertEqual(merge_media_links([first], [other, reel]), [reel, other])

    def test_page_without_media_links_yields_nothing(self) -> None:
        self.assertEqual(discover_media_links(fixture("private_profile.html"), "davvvat"), [])


class ProfileStateTests(unittest.TestCase):
    def test_private_notice_is_detected(self) -> None:
        self.assertEqual(detect_profile_state(fixture("private_profile.html")), PROFILE_PRIVATE)

    def test_persian_private_notice_is_detected(self) -> None:
        self.assertEqual(detect_profile_state("<div>این حساب خصوصی است</div>"), PROFILE_PRIVATE)

    def test_unavailable_notice_with_typographic_apostrophe_is_detected(self) -> None:
        self.assertEqual(detect_profile_state(fixture("unavailable_profile.html")), PROFILE_UNAVAILABLE)

    def test_ui_strings_inside_scripts_are_ignored(self) -> None:
        self.assertEqual(detect_profile_state(fixture("profile_davvvat.html")), PROFILE_UNKNOWN)


class MediaPageTests(unittest.TestCase):
    def test_caption_heading_is_extracted_with_line_breaks_and_linked_text(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)

        self.assertEqual(data.caption, "کارگاه طراحی شهری\nجمعه ساعت ۱۷ #رویداد با @venue.tehran")
        self.assertEqual(data.caption_source, "h1")

    def test_published_at_comes_from_the_time_linking_to_the_media_not_a_comment(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)

        self.assertEqual(data.published_at, datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(data.published_at_source, "time[datetime]:media-link")

    def test_thumbnail_comes_from_open_graph(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)
        self.assertEqual(data.image_url, "https://cdn.example.test/post1-thumb.jpg")

    def test_open_graph_caption_is_only_a_fallback(self) -> None:
        data = parse_media_page(fixture("reel_page_og_only.html"), REEL1)

        self.assertEqual(data.caption, "Rooftop concert: Friday 19:00")
        self.assertEqual(data.caption_source, "og:description")
        self.assertIsNone(data.published_at)
        self.assertEqual(data.published_at_source, "none")

    def test_reel_link_is_classified_as_reel(self) -> None:
        self.assertEqual(parse_media_page(fixture("reel_page_og_only.html"), REEL1).kind, ORIGIN_REEL)

    def test_post_redirected_to_a_reel_url_is_classified_as_reel(self) -> None:
        data = parse_media_page(
            fixture("post_page.html"), POST1, final_url="https://www.instagram.com/reel/POST1/?igsh=x"
        )
        self.assertEqual(data.kind, ORIGIN_REEL)

    def test_post_link_stays_a_post(self) -> None:
        data = parse_media_page(
            fixture("post_page.html"), POST1, final_url="https://www.instagram.com/p/POST1/"
        )
        self.assertEqual(data.kind, ORIGIN_POST)

    def test_article_timestamp_is_used_when_no_media_link_carries_one(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><time datetime="2026-09-09T10:00:00+03:30"></time></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))

        self.assertEqual(data.published_at, datetime(2026, 9, 9, 6, 30, tzinfo=timezone.utc))
        self.assertEqual(data.published_at_source, "time[datetime]:article")

    def test_naive_timestamp_is_not_assigned_a_timezone(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><a href="/p/X1/"><time datetime="2026-09-09T14:30:00"></time></a></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))
        self.assertIsNone(data.published_at)

    def test_comment_timestamp_alone_is_never_used(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><a href="/p/X1/c/1/"><time datetime="2026-09-10T08:00:00Z"></time></a></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))
        self.assertIsNone(data.published_at)

    def test_missing_caption_stays_null(self) -> None:
        html = '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))

        self.assertIsNone(data.caption)
        self.assertEqual(data.caption_source, "none")

    def test_page_without_media_content_is_malformed(self) -> None:
        with self.assertRaises(MalformedMediaPageError):
            parse_media_page(fixture("malformed_media_page.html"), POST1)

    def test_page_showing_different_media_is_malformed(self) -> None:
        with self.assertRaises(MalformedMediaPageError):
            parse_media_page(fixture("post_page.html"), REEL1)


class CaptionTokenTests(unittest.TestCase):
    def test_hashtags_include_persian_words_with_zero_width_non_joiner(self) -> None:
        self.assertEqual(caption_hashtags("#رویداد و #کارگاه‌ها #event"), ("رویداد", "کارگاه‌ها", "event"))

    def test_mentions_are_instagram_usernames(self) -> None:
        self.assertEqual(caption_mentions("با @venue.tehran و @jabama.events"), ("venue.tehran", "jabama.events"))

    def test_missing_caption_has_no_tokens(self) -> None:
        self.assertEqual(caption_hashtags(None), ())
        self.assertEqual(caption_mentions(None), ())


if __name__ == "__main__":
    unittest.main()
