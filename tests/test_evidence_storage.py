import tempfile
import unittest
from pathlib import Path

from gatherradar.domain import EvidenceFragment, EvidenceKind
from gatherradar.storage import JsonlEvidenceStore


def fragment(version='1', text='کارگاه سفالگری'):
    return EvidenceFragment.create(
        raw_item_id='instagram:source:ABC', kind=EvidenceKind.IMAGE_OCR,
        text=text, raw_text=text + '\n', source_url='https://www.instagram.com/p/ABC/',
        local_asset_path='data/media/image.png', asset_hash='a' * 64,
        extraction_engine='fake', extraction_version=version,
        extraction_config='fas+eng',
    )


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'evidence' / 'source.jsonl'
        self.store = JsonlEvidenceStore(self.path)

    def test_roundtrip_preserves_persian_and_provenance(self):
        expected = fragment()
        self.store.append_new([expected])
        self.assertEqual(self.store.read().fragments, (expected,))
        self.assertIn('کارگاه سفالگری', self.path.read_text(encoding='utf-8'))

    def test_same_fragment_is_idempotent(self):
        first = self.store.append_new([fragment()])
        second = self.store.append_new([fragment()])
        self.assertEqual((first.new, first.already_existing), (1, 0))
        self.assertEqual((second.new, second.already_existing), (0, 1))
        self.assertEqual(len(self.path.read_text(encoding='utf-8').splitlines()), 1)

    def test_engine_change_appends_auditable_observation(self):
        self.store.append_new([fragment('1')])
        result = self.store.append_new([fragment('2')])
        self.assertEqual(result.new, 1)
        self.assertEqual(len(self.store.read().fragments), 2)

    def test_changed_ocr_output_is_auditable(self):
        self.store.append_new([fragment(text='old')])
        self.store.append_new([fragment(text='new')])
        self.assertEqual([item.text for item in self.store.read().fragments], ['old', 'new'])

    def test_malformed_lines_are_isolated(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{bad}\n', encoding='utf-8')
        self.store.append_new([fragment()])
        result = self.store.read()
        self.assertEqual(len(result.fragments), 1)
        self.assertEqual(len(result.malformed), 1)
        self.assertNotIn('کارگاه', result.malformed[0])


if __name__ == '__main__':
    unittest.main()
