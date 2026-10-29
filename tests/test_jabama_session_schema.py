"""Jabama `soldOut` / non-empty `timeslots` boundary and the value-free evidence report.

The owner's October 29 crawl reported these property names only. Their types and
meaning have not been inspected, so they stay unverified (sessions reviewable,
never actionable, no availability read) until the structural report is examined.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, time, timezone
from pathlib import Path

from gatherradar.cli import main
from gatherradar.collectors.websites.html import parse_html
from gatherradar.collectors.websites.jabama_sessions import describe_embedded_sessions
from gatherradar.domain import EventStatus
from gatherradar.orchestration.session_schema_report import build_report
from gatherradar.review.readiness import DataReadiness, assess_readiness
from gatherradar.review.relevance import assess_relevance
from gatherradar.storage import JsonlRawItemStore
from test_jabama_session_pipeline import collected, pipeline
from test_jabama_sessions import SESSION, URL, _page, _result

SECRET_SLOT = {'id': 'slot-PRIVATE-77', 'startIso': '2026-10-30T07:30:00Z', 'capacity': 4, 'label': 'PRIVATE-LABEL'}
BEFORE = datetime(2026, 9, 20, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 5, tzinfo=timezone.utc)


def page(sessions, extra=''):
    return _page(sessions).replace(
        'ساخت یک اثر با راهنمایی مربی.', 'ساخت یک اثر با راهنمایی مربی.</div><div>میزبان: استودیو نمونه، تهران' + extra)


class SoldOutBoundaryTests(unittest.TestCase):
    def test_sold_out_is_reported_with_its_shape_but_stays_unverified(self):
        result = _result(_page([{**SESSION, 'soldOut': True}]))
        value, = result.sessions
        self.assertEqual(value.schema_status, 'unverified_properties')
        self.assertIsNone(value.remaining_seats)  # no availability read or inferred
        self.assertIsNone(value.enabled)
        self.assertEqual(result.drift_keys, ('soldOut',))
        shape, = result.drift_shapes
        self.assertEqual(shape['keys']['soldOut'], {'type': 'bool', 'value': True})
        self.assertEqual(shape['keys']['startIso'], {'type': 'string', 'form': 'iso_datetime', 'length': '11-40'})
        self.assertNotIn('demo-session-a', json.dumps(shape))  # identifiers are never copied

    def test_unexpected_types_are_described_not_interpreted(self):
        for value, expected in (('yes', 'string'), (1, 'integer'), (None, 'null'), ([True], 'array')):
            with self.subTest(value=value):
                result = _result(_page([{**SESSION, 'soldOut': value}]))
                self.assertEqual(result.sessions[0].schema_status, 'unverified_properties')
                self.assertEqual(result.drift_shapes[0]['keys']['soldOut']['type'], expected)

    def test_sold_out_session_is_neither_expired_nor_actionable_nor_a_status(self):
        raw = collected(page([{**SESSION, 'soldOut': True}]))
        _, outcome = pipeline(raw)
        event, = outcome.events
        self.assertNotEqual(event.status, EventStatus.SOLD_OUT)
        self.assertNotEqual(event.status, EventStatus.EXPIRED)
        self.assertEqual(assess_relevance(event, BEFORE).disposition, 'needs_schedule_review')
        self.assertEqual(assess_relevance(event, BEFORE).reason, 'unresolved_sessions')
        self.assertEqual(assess_readiness(event).status, DataReadiness.SCHEDULE)
        # Once the session's own date has passed it is expired, sold out or not.
        self.assertEqual(assess_relevance(event, AFTER).disposition, 'expired')

    def test_page_sold_out_wording_and_session_flag_are_not_merged(self):
        raw = collected(page([{**SESSION, 'soldOut': False}], '</div><div>تکمیل ظرفیت'))
        _, outcome = pipeline(raw)
        event, = outcome.events
        self.assertEqual(event.availability_text, 'تکمیل ظرفیت')  # the page's own wording
        self.assertTrue(all(o.availability_text is None and o.remaining_seats is None for o in event.occurrences))

    def test_multiple_sessions_keep_identity_date_clock_and_timezone(self):
        sessions = [{**SESSION, 'id': 'a', 'startIso': '2026-09-30T11:30:00Z', 'soldOut': True},
                    {**SESSION, 'id': 'b', 'startIso': '2026-09-30T14:30:00Z', 'soldOut': False}]
        _, outcome = pipeline(collected(page(sessions)))
        event, = outcome.events
        self.assertEqual([(o.source_session_id, o.start_time, o.timezone, o.starts_at.utcoffset().total_seconds())
                          for o in event.occurrences],
                         [('a', time(15), 'Asia/Tehran', 12600.0), ('b', time(18), 'Asia/Tehran', 12600.0)])
        self.assertEqual(len({o.occurrence_id for o in event.occurrences}), 2)  # never collapsed


class TimeslotBoundaryTests(unittest.TestCase):
    def test_empty_timeslots_are_documented_and_non_empty_are_refused_with_a_shape(self):
        self.assertEqual(_result(_page()).sessions[0].schema_status, None)
        result = _result(_page([{**SESSION, 'timeslots': [SECRET_SLOT, {**SECRET_SLOT, 'capacity': 0}]}]))
        self.assertEqual(result.sessions, ())
        self.assertIn('embedded_session_drift_timeslots', result.diagnostics)
        slots = result.drift_shapes[0]['keys']['timeslots']
        self.assertEqual((slots['type'], slots['length']), ('array', 2))
        keys = slots['items'][0]['keys']
        self.assertEqual(keys['startIso']['form'], 'iso_datetime')
        self.assertEqual({keys['capacity']['sign'], slots['items'][1]['keys']['capacity']['sign']},
                         {'positive', 'zero'})
        text = json.dumps(result.drift_shapes)
        for private in ('PRIVATE', 'slot-', '07:30'):
            self.assertNotIn(private, text)

    def test_unreadable_timeslot_sessions_stay_in_schedule_review(self):
        _, outcome = pipeline(collected(page([{**SESSION, 'timeslots': [SECRET_SLOT], 'soldOut': True}])))
        event, = outcome.events
        self.assertEqual(event.occurrences, ())
        self.assertIn('source_sessions_unreadable', assess_readiness(event).reasons)

    def test_envelope_failures_name_their_stage(self):
        moved = _page().replace('routes/events.$id', 'routes/experiences.$id')
        self.assertEqual(_result(moved).diagnostics,
                         ('embedded_sessions_schema_drift', 'embedded_sessions_drift_route'))
        self.assertEqual(_result(_page() + _page()).diagnostics,
                         ('embedded_sessions_schema_drift', 'embedded_sessions_drift_payload_count'))
        self.assertEqual(_result(_page([])).diagnostics, ('embedded_sessions_empty',))


class EvidenceReportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        raw = collected(page([{**SESSION, 'soldOut': True, 'pricePerPerson': 999999},
                              {**SESSION, 'id': 'second', 'timeslots': [SECRET_SLOT]}]))
        self.raw = raw
        store = self.root / 'data' / 'raw' / 'website' / 'jabama_test.jsonl'
        JsonlRawItemStore(store).append_new([raw])
        self.saved = self.root / 'saved page.html'
        self.saved.write_text(page([{**SESSION, 'soldOut': True}, {**SESSION, 'id': 'x', 'soldOut': False}]),
                              encoding='utf-8')

    def test_collector_retains_value_free_shapes_and_reruns_are_stable(self):
        shapes = self.raw.raw_metadata['source_session_drift_shapes']
        self.assertEqual(len(shapes), 2)
        self.assertEqual(self.raw.content_hash, collected(page([{**SESSION, 'soldOut': True, 'pricePerPerson': 999999},
                              {**SESSION, 'id': 'second', 'timeslots': [SECRET_SLOT]}])).content_hash)

    def test_report_is_bounded_sanitized_and_read_only(self):
        before = sorted(p.relative_to(self.root) for p in self.root.rglob('*'))
        report = build_report(self.root / 'data', [self.saved])
        self.assertEqual(sorted(p.relative_to(self.root) for p in self.root.rglob('*')), before)
        row, = report['observations']
        self.assertEqual((row['source_id'], row['public_event_id'], row['observation_id']),
                         ('jabama_test', 'demo-event', self.raw.id))
        self.assertEqual(row['unexpected_session_properties'], ['soldOut'])
        self.assertIn('embedded_session_drift_timeslots', row['session_diagnostics'])
        self.assertEqual(row['stored_session_status'], {'unverified_properties': 1})
        self.assertEqual(report['summary']['unexpected_properties'], {'soldOut': 1})
        saved, = report['saved_pages']
        self.assertEqual(saved['file'], 'saved page.html')  # never the local path
        self.assertEqual(saved['unknown_keys'], ['soldOut'])
        self.assertEqual(saved['key_summary']['soldOut'], {'types': {'bool': 2}, 'true': 1, 'false': 1,
                                                          'present_in': 2})
        text = json.dumps(report, ensure_ascii=False)
        for private in ('PRIVATE', '999999', 'demo-session-a', 'UNRELATED REVIEW', str(self.root), 'کارگاه نمونه'):
            self.assertNotIn(private, text)

    def test_saved_page_without_envelope_or_route(self):
        self.assertEqual(describe_embedded_sessions(parse_html('<html></html>'))['envelope'], 'absent')
        moved = describe_embedded_sessions(parse_html(_page().replace('routes/events.$id', 'routes/other')))
        self.assertEqual(moved['route'], 'missing')

    def test_cli_writes_only_the_requested_report(self):
        output = self.root / 'report.json'
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(['diagnose', 'jabama-sessions', '--data-dir', str(self.root / 'data'),
                         '--html', str(self.saved), '--output', str(output)])
        self.assertEqual(code, 0)
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['summary']['observations'], 1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['diagnose', 'jabama-sessions', '--data-dir', str(self.root),
                                   '--output', str(self.root / 'report.txt')]), 2)


if __name__ == '__main__':
    unittest.main()
