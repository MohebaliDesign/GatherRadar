import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from extraction_fakes import (
    ENGLISH_EVENT_FACTS,
    ENGLISH_EVENT_TEXT,
    ENGLISH_NON_EVENT_TEXT,
    PERSIAN_EVENT_FACTS,
    PERSIAN_EVENT_TEXT,
    PERSIAN_NON_EVENT_TEXT,
    PUBLISHED_AT,
    AlwaysEventProvider,
    FailingProvider,
    InvalidOutputProvider,
    NonEventProvider,
    ScriptedProvider,
    make_raw_item,
    make_source,
)
from gatherradar.extraction import (
    EventExtractionService,
    ExtractedEventFacts,
    ExtractionInput,
    ExtractionStatus,
    InvalidExtractionOutputError,
    build_candidate_id,
    build_extraction_input,
    validate_extracted_facts,
)

ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_FIELDS = tuple(field.name for field in fields(ExtractedEventFacts) if field.name != "is_event")


def extract(provider, raw_item=None, source=None):
    raw_item = raw_item if raw_item is not None else make_raw_item(PERSIAN_EVENT_TEXT)
    return EventExtractionService(provider).extract(raw_item, source)


class ExtractionInputTests(unittest.TestCase):
    def test_input_carries_only_deliberate_source_evidence(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        extraction_input = build_extraction_input(raw_item, make_source())

        self.assertEqual(
            extraction_input,
            ExtractionInput(
                raw_item_id="instagram:davvvat:EVT1",
                source_id="davvvat_instagram",
                source_type="instagram",
                raw_text=PERSIAN_EVENT_TEXT,
                content_url="https://www.instagram.com/p/EVT1/",
                content_type="reel",
                published_at=PUBLISHED_AT,
                author="davvvat",
                locale="fa-IR",
                timezone="Asia/Tehran",
                city_hint="Tehran",
            ),
        )

    def test_raw_metadata_is_not_passed_to_the_provider(self) -> None:
        names = {field.name for field in fields(ExtractionInput)}
        self.assertNotIn("raw_metadata", names)
        self.assertNotIn("image_url", names)

    def test_input_without_source_context_leaves_context_empty(self) -> None:
        extraction_input = build_extraction_input(make_raw_item(ENGLISH_EVENT_TEXT))

        self.assertIsNone(extraction_input.locale)
        self.assertIsNone(extraction_input.timezone)
        self.assertIsNone(extraction_input.city_hint)

    def test_source_context_must_match_the_raw_item_source(self) -> None:
        other = make_source(id="vadoostan_instagram", url="https://www.instagram.com/vadoostan/", username="vadoostan")
        with self.assertRaises(ValueError):
            build_extraction_input(make_raw_item(ENGLISH_EVENT_TEXT), other)


class ProviderCallTests(unittest.TestCase):
    def test_provider_is_called_exactly_once_per_eligible_item(self) -> None:
        provider = AlwaysEventProvider(PERSIAN_EVENT_FACTS)
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        extract(provider, raw_item, make_source())

        self.assertEqual(provider.calls, [build_extraction_input(raw_item, make_source())])

    def test_empty_raw_text_skips_the_provider(self) -> None:
        provider = AlwaysEventProvider()

        outcome = extract(provider, make_raw_item(""))

        self.assertEqual(outcome.status, ExtractionStatus.SKIPPED)
        self.assertEqual(provider.calls, [])
        self.assertTrue(outcome.reason)

    def test_whitespace_only_raw_text_is_also_skipped(self) -> None:
        provider = AlwaysEventProvider()
        outcome = extract(provider, make_raw_item(" \n\t "))

        self.assertEqual(outcome.status, ExtractionStatus.SKIPPED)
        self.assertEqual(provider.calls, [])

    def test_skipped_item_is_not_classified_as_a_non_event(self) -> None:
        outcome = extract(NonEventProvider(), make_raw_item(""))
        self.assertIsNone(outcome.candidate)


class CandidateMappingTests(unittest.TestCase):
    def test_event_output_maps_onto_event_candidate(self) -> None:
        outcome = extract(AlwaysEventProvider(PERSIAN_EVENT_FACTS), source=make_source())

        self.assertEqual(outcome.status, ExtractionStatus.EXTRACTED)
        self.assertIsNone(outcome.reason)
        self.assertEqual(outcome.provider_name, "always-event-test-provider")
        self.assertTrue(outcome.candidate.is_event)
        for name in SEMANTIC_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(getattr(outcome.candidate, name), getattr(PERSIAN_EVENT_FACTS, name))

    def test_non_event_output_maps_with_no_semantic_fields(self) -> None:
        outcome = extract(NonEventProvider(), make_raw_item(PERSIAN_NON_EVENT_TEXT, shortcode="NON1"))

        self.assertEqual(outcome.status, ExtractionStatus.EXTRACTED)
        self.assertFalse(outcome.candidate.is_event)
        for name in SEMANTIC_FIELDS:
            with self.subTest(field=name):
                self.assertIsNone(getattr(outcome.candidate, name))

    def test_unknown_fields_remain_none_and_an_event_needs_no_title(self) -> None:
        candidate = extract(AlwaysEventProvider(ExtractedEventFacts(is_event=True))).candidate

        self.assertTrue(candidate.is_event)
        for name in SEMANTIC_FIELDS:
            with self.subTest(field=name):
                self.assertIsNone(getattr(candidate, name))

    def test_whitespace_only_fields_become_none(self) -> None:
        facts = ExtractedEventFacts(
            is_event=True, title="   ", summary="\n\t", venue_name="", address=" ", price_text="\n"
        )
        candidate = extract(AlwaysEventProvider(facts)).candidate

        for name in ("title", "summary", "venue_name", "address", "price_text"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(candidate, name))

    def test_non_blank_text_is_kept_exactly(self) -> None:
        facts = ExtractedEventFacts(is_event=True, title="  Design meetup  ")
        self.assertEqual(extract(AlwaysEventProvider(facts)).candidate.title, "  Design meetup  ")

    def test_persian_text_and_emoji_are_preserved_exactly(self) -> None:
        provider = AlwaysEventProvider(PERSIAN_EVENT_FACTS)
        candidate = extract(provider).candidate

        self.assertEqual(provider.calls[0].raw_text, PERSIAN_EVENT_TEXT)
        self.assertEqual(candidate.address, "نیاوران، سه راه یاسر، بن‌بست بهار")
        self.assertEqual(candidate.summary, "دورهمی طراحی در خانه هنرمندان 🎨")
        self.assertIn("🎨", provider.calls[0].raw_text)

    def test_english_text_is_preserved_exactly(self) -> None:
        provider = AlwaysEventProvider(ENGLISH_EVENT_FACTS)
        candidate = extract(provider, make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2")).candidate

        self.assertEqual(provider.calls[0].raw_text, ENGLISH_EVENT_TEXT)
        self.assertEqual(candidate.summary, "A design meetup at Studio North on Friday at 7 PM ✨")
        self.assertEqual(candidate.registration_url, "https://tickets.example.test/design-meetup")

    def test_no_normalization_happens_in_this_layer(self) -> None:
        candidate = extract(AlwaysEventProvider(PERSIAN_EVENT_FACTS), source=make_source()).candidate

        self.assertEqual(candidate.source_date_text, "۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲")
        self.assertEqual(candidate.price_text, "ورودی ۳۵۰ هزار تومان")
        self.assertEqual(candidate.category, "workshop")
        self.assertIsNone(candidate.starts_at)
        self.assertIsNone(candidate.ends_at)
        self.assertIsNone(candidate.price_amount)
        self.assertIsNone(candidate.currency)

    def test_city_hint_context_is_never_copied_into_city(self) -> None:
        provider = AlwaysEventProvider(PERSIAN_EVENT_FACTS)
        candidate = extract(provider, source=make_source(city_hint="Tehran")).candidate

        self.assertEqual(provider.calls[0].city_hint, "Tehran")
        self.assertIsNone(candidate.city)


class ProvenanceTests(unittest.TestCase):
    def test_raw_item_id_and_evidence_url_come_from_the_raw_item(self) -> None:
        raw_item = make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2")

        candidate = extract(AlwaysEventProvider(ENGLISH_EVENT_FACTS), raw_item).candidate

        self.assertEqual(candidate.raw_item_id, raw_item.id)
        self.assertEqual(candidate.evidence_url, raw_item.content_url)
        self.assertNotEqual(candidate.evidence_url, ENGLISH_EVENT_FACTS.registration_url)

    def test_output_that_tries_to_supply_provenance_is_rejected(self) -> None:
        spoofed = SimpleNamespace(
            is_event=True, raw_item_id="instagram:someone:SPOOF", evidence_url="https://evil.example.test/"
        )

        outcome = extract(InvalidOutputProvider(spoofed))

        self.assertEqual(outcome.status, ExtractionStatus.INVALID_OUTPUT)
        self.assertIsNone(outcome.candidate)

    def test_provider_output_contract_has_no_provenance_fields(self) -> None:
        names = {field.name for field in fields(ExtractedEventFacts)}
        self.assertTrue(names.isdisjoint({"candidate_id", "raw_item_id", "evidence_url"}))


class CandidateIdTests(unittest.TestCase):
    def test_candidate_ids_are_deterministic(self) -> None:
        first = build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT))
        again = build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT))

        self.assertEqual(first, again)
        self.assertTrue(first.startswith("candidate:"))
        int(first.removeprefix("candidate:"), 16)

    def test_same_observation_extracts_to_the_same_candidate_id(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        first = extract(AlwaysEventProvider(PERSIAN_EVENT_FACTS), raw_item).candidate
        second = extract(AlwaysEventProvider(PERSIAN_EVENT_FACTS), raw_item).candidate

        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.candidate_id, build_candidate_id(raw_item))

    def test_changed_content_hash_gives_a_different_candidate_id(self) -> None:
        original = make_raw_item(PERSIAN_EVENT_TEXT, content_hash="a" * 64)
        edited = make_raw_item(PERSIAN_EVENT_TEXT, content_hash="b" * 64)

        self.assertEqual(original.id, edited.id)
        self.assertNotEqual(build_candidate_id(original), build_candidate_id(edited))

    def test_different_raw_items_give_different_candidate_ids(self) -> None:
        self.assertNotEqual(
            build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT, shortcode="A1", content_hash="c" * 64)),
            build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT, shortcode="A2", content_hash="c" * 64)),
        )

    def test_candidate_id_does_not_depend_on_the_provider(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        from_event_provider = extract(AlwaysEventProvider(PERSIAN_EVENT_FACTS), raw_item).candidate
        from_other_provider = extract(NonEventProvider(), raw_item).candidate

        self.assertEqual(from_event_provider.candidate_id, from_other_provider.candidate_id)


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, output: object) -> None:
        outcome = extract(InvalidOutputProvider(output))
        self.assertEqual(outcome.status, ExtractionStatus.INVALID_OUTPUT)
        self.assertIsNone(outcome.candidate)
        self.assertTrue(outcome.reason)

    def test_invalid_confidence_is_rejected(self) -> None:
        for confidence in (1.2, -0.1, float("nan"), float("inf"), True, "0.8"):
            with self.subTest(confidence=confidence):
                self.assert_invalid(ExtractedEventFacts(is_event=True, extraction_confidence=confidence))

    def test_boundary_confidence_values_are_accepted(self) -> None:
        for confidence in (0, 1, 0.0, 0.5, 1.0):
            with self.subTest(confidence=confidence):
                candidate = extract(
                    AlwaysEventProvider(ExtractedEventFacts(is_event=True, extraction_confidence=confidence))
                ).candidate
                self.assertEqual(candidate.extraction_confidence, float(confidence))

    def test_invalid_registration_url_is_rejected(self) -> None:
        for url in ("tickets.example.test/meetup", "javascript:alert(1)", "ftp://example.test/meetup", "https://"):
            with self.subTest(url=url):
                self.assert_invalid(ExtractedEventFacts(is_event=True, registration_url=url))

    def test_http_and_https_registration_urls_are_accepted(self) -> None:
        for url in ("http://tickets.example.test/meetup", "https://tickets.example.test/meetup?id=1"):
            with self.subTest(url=url):
                facts = ExtractedEventFacts(is_event=True, registration_url=url)
                self.assertEqual(extract(AlwaysEventProvider(facts)).candidate.registration_url, url)

    def test_is_event_must_be_a_boolean(self) -> None:
        for value in ("true", 1, None):
            with self.subTest(is_event=value):
                self.assert_invalid(ExtractedEventFacts(is_event=value))

    def test_text_fields_must_be_text(self) -> None:
        self.assert_invalid(ExtractedEventFacts(is_event=True, title=123))

    def test_unsupported_event_format_is_rejected(self) -> None:
        for event_format in ("in-person", "unknown", "offline"):
            with self.subTest(event_format=event_format):
                self.assert_invalid(ExtractedEventFacts(is_event=True, event_format=event_format))

    def test_supported_event_formats_are_accepted(self) -> None:
        for event_format in ("in_person", "online", "hybrid"):
            with self.subTest(event_format=event_format):
                facts = ExtractedEventFacts(is_event=True, event_format=event_format)
                self.assertEqual(extract(AlwaysEventProvider(facts)).candidate.event_format, event_format)

    def test_output_of_the_wrong_type_is_rejected(self) -> None:
        with self.assertRaises(InvalidExtractionOutputError):
            validate_extracted_facts({"is_event": True})
        self.assert_invalid({"is_event": True})


class FailureIsolationTests(unittest.TestCase):
    def test_provider_error_becomes_a_provider_failure_outcome(self) -> None:
        outcome = extract(FailingProvider())

        self.assertEqual(outcome.status, ExtractionStatus.PROVIDER_FAILED)
        self.assertIsNone(outcome.candidate)
        self.assertEqual(outcome.reason, "test provider is unavailable")
        self.assertEqual(outcome.provider_name, "failing-test-provider")

    def test_provider_reported_invalid_output_is_isolated(self) -> None:
        raw_item = make_raw_item(ENGLISH_NON_EVENT_TEXT, shortcode="NON2")
        provider = ScriptedProvider({raw_item.id: InvalidExtractionOutputError("response was not valid JSON")})

        outcome = extract(provider, raw_item)

        self.assertEqual(outcome.status, ExtractionStatus.INVALID_OUTPUT)
        self.assertEqual(outcome.reason, "response was not valid JSON")

    def test_unexpected_provider_bugs_are_not_swallowed(self) -> None:
        raw_item = make_raw_item(ENGLISH_EVENT_TEXT)
        provider = ScriptedProvider({raw_item.id: RuntimeError("adapter bug")})

        with self.assertRaises(RuntimeError):
            extract(provider, raw_item)


class NoNetworkTests(unittest.TestCase):
    def test_extraction_runs_without_any_network_access(self) -> None:
        samples = (
            (make_raw_item(PERSIAN_EVENT_TEXT, shortcode="EVT1"), PERSIAN_EVENT_FACTS),
            (make_raw_item(PERSIAN_NON_EVENT_TEXT, shortcode="NON1"), ExtractedEventFacts(is_event=False, language="fa")),
            (make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2"), ENGLISH_EVENT_FACTS),
            (make_raw_item(ENGLISH_NON_EVENT_TEXT, shortcode="NON2"), ExtractedEventFacts(is_event=False, language="en")),
        )
        provider = ScriptedProvider({raw_item.id: facts for raw_item, facts in samples})
        service = EventExtractionService(provider)

        with mock.patch("socket.socket.connect", side_effect=AssertionError("network used")):
            outcomes = [service.extract(raw_item, make_source()) for raw_item, _ in samples]

        self.assertTrue(all(outcome.status is ExtractionStatus.EXTRACTED for outcome in outcomes))

    def test_extraction_code_has_no_provider_sdk_or_network_imports(self) -> None:
        paths = sorted((ROOT / "src" / "gatherradar" / "extraction").glob("*.py"))
        paths.append(ROOT / "src" / "gatherradar" / "orchestration" / "extraction_run.py")
        forbidden = ("openai", "anthropic", "requests", "httpx", "http.client", "urllib.request", "socket")

        for path in paths:
            source = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, source)

    def test_no_ai_provider_dependency_is_declared(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        self.assertNotIn("openai", pyproject)
        self.assertNotIn("anthropic", pyproject)


if __name__ == "__main__":
    unittest.main()
