import os
import tempfile
import unittest
from pathlib import Path

from extraction_fakes import (
    ENGLISH_EVENT_FACTS,
    ENGLISH_EVENT_TEXT,
    ENGLISH_NON_EVENT_TEXT,
    PERSIAN_EVENT_FACTS,
    PERSIAN_EVENT_TEXT,
    PERSIAN_NON_EVENT_TEXT,
    ScriptedProvider,
    make_raw_item,
    make_source,
)
from gatherradar.domain import EventCandidate
from gatherradar.extraction import (
    EventExtractionService,
    ExtractedEventFacts,
    ExtractionStatus,
    ProviderExtractionError,
)
from gatherradar.orchestration.extraction_run import run_event_extraction


def batch():
    """Items in an order that puts failures before successes."""
    items = [
        make_raw_item("Provider will fail on this one", shortcode="FAIL1"),
        make_raw_item(PERSIAN_EVENT_TEXT, shortcode="EVT1"),
        make_raw_item("", shortcode="EMPTY1"),
        make_raw_item("Provider returns garbage for this one", shortcode="BAD1"),
        make_raw_item(PERSIAN_NON_EVENT_TEXT, shortcode="NON1"),
        make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2"),
        make_raw_item(ENGLISH_NON_EVENT_TEXT, shortcode="NON2"),
    ]
    responses = {
        "instagram:davvvat:FAIL1": ProviderExtractionError("scripted provider failure"),
        "instagram:davvvat:EVT1": PERSIAN_EVENT_FACTS,
        "instagram:davvvat:BAD1": {"is_event": "maybe"},
        "instagram:davvvat:NON1": ExtractedEventFacts(is_event=False, language="fa"),
        "instagram:davvvat:EVT2": ENGLISH_EVENT_FACTS,
        "instagram:davvvat:NON2": ExtractedEventFacts(is_event=False, language="en"),
    }
    return items, ScriptedProvider(responses)


class ExtractionRunTests(unittest.TestCase):
    def run_batch(self, **kwargs):
        items, provider = batch()
        summary = run_event_extraction(items, EventExtractionService(provider), **kwargs)
        return summary, provider

    def test_summary_counts_events_non_events_skipped_and_failed(self) -> None:
        summary, _ = self.run_batch()

        self.assertEqual(summary.observed, 7)
        self.assertEqual(summary.extracted, 4)
        self.assertEqual(summary.events, 2)
        self.assertEqual(summary.non_events, 2)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.failed, 2)

    def test_batch_continues_after_failed_items(self) -> None:
        summary, _ = self.run_batch()

        self.assertEqual(
            [outcome.status for outcome in summary.outcomes],
            [
                ExtractionStatus.PROVIDER_FAILED,
                ExtractionStatus.EXTRACTED,
                ExtractionStatus.SKIPPED,
                ExtractionStatus.INVALID_OUTPUT,
                ExtractionStatus.EXTRACTED,
                ExtractionStatus.EXTRACTED,
                ExtractionStatus.EXTRACTED,
            ],
        )
        self.assertEqual(
            [candidate.raw_item_id for candidate in summary.candidates],
            ["instagram:davvvat:EVT1", "instagram:davvvat:NON1", "instagram:davvvat:EVT2", "instagram:davvvat:NON2"],
        )

    def test_provider_is_called_once_per_eligible_item(self) -> None:
        _, provider = self.run_batch()

        self.assertEqual(len(provider.calls), 6)
        self.assertNotIn("instagram:davvvat:EMPTY1", [call.raw_item_id for call in provider.calls])

    def test_source_context_is_looked_up_by_source_id(self) -> None:
        _, provider = self.run_batch(sources={"davvvat_instagram": make_source()})

        self.assertTrue(all(call.locale == "fa-IR" for call in provider.calls))
        self.assertTrue(all(call.city_hint == "Tehran" for call in provider.calls))

    def test_items_without_known_source_get_no_context(self) -> None:
        _, provider = self.run_batch(sources={})
        self.assertTrue(all(call.locale is None and call.timezone is None for call in provider.calls))

    def test_candidates_are_returned_in_memory_and_nothing_is_persisted(self) -> None:
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as workdir:
            os.chdir(workdir)
            try:
                summary, _ = self.run_batch()
                written = list(Path(workdir).iterdir())
            finally:
                os.chdir(original_cwd)

        self.assertEqual(written, [])
        self.assertEqual(len(summary.candidates), 4)
        self.assertTrue(all(isinstance(candidate, EventCandidate) for candidate in summary.candidates))

    def test_summary_reports_the_provider_name(self) -> None:
        summary, _ = self.run_batch()
        self.assertEqual(summary.provider_name, "scripted-test-provider")

    def test_any_iterable_of_raw_items_is_accepted(self) -> None:
        items, provider = batch()
        summary = run_event_extraction((item for item in items), EventExtractionService(provider))
        self.assertEqual(summary.observed, 7)

    def test_empty_batch_has_zero_counts(self) -> None:
        summary = run_event_extraction([], EventExtractionService(ScriptedProvider({})))

        self.assertEqual(
            (summary.observed, summary.extracted, summary.events, summary.non_events, summary.skipped, summary.failed),
            (0, 0, 0, 0, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
