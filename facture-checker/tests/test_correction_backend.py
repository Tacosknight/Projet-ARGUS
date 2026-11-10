import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Prevent application initialization from copying user data into the test directory.
_app_data = tempfile.TemporaryDirectory()
os.environ['ARGUS_DATA_DIR'] = _app_data.name
from core import app_paths
Path(_app_data.name, 'data').mkdir()
with patch.object(app_paths, 'ensure_app_directories'):
    from web import app as web
from storage.database import InvoiceDatabase
from core.validator import generate_invoice_hash
from fastapi.testclient import TestClient


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = InvoiceDatabase(str(Path(self.tmp.name) / 'test.db'))
        self.patch_db = patch.object(web, 'db', self.db)
        self.patch_db.start()
        self.patch_excel = patch.object(web, 'refresh_excel', return_value=[])
        self.excel_mock = self.patch_excel.start()
        self.client = TestClient(web.app)
        self.id = self.create('A', 'a.jpg')

    def tearDown(self):
        self.patch_excel.stop()
        self.patch_db.stop()
        self.tmp.cleanup()

    def create(self, number, filename):
        return self.db.save_invoice({'filename': filename, 'siret': '73282932000074',
            'numero_facture': number, 'date_facture': '2025-01-01', 'montant_ht': 100,
            'montant_tva': 20, 'montant_ttc': 120, 'serial_numbers': ['123456'],
            'product_items': [{'product_name': 'A', 'serial_number': '123456', 'quantity': 2},
                              {'product_name': 'B', 'serial_number': '123456', 'extra': 'keep'}],
            'unique_hash': generate_invoice_hash('73282932000074', '2025-01-01', number, 120),
            'status': 'VALIDE'})

    def get(self):
        return self.client.get(f'/api/invoices/{self.id}').json()

    def put(self, data):
        return self.client.put(f'/api/invoices/{self.id}', json=data)

    def test_partial_correction_revision_and_revalidation(self):
        original = self.get()
        r = self.put({'expected_revision': original['revision'], 'patient_nom': 'Alice',
                      'serial_corrections': [{'serial_index': 0, 'item_indices': [0], 'value': '934 534'}]})
        self.assertEqual(r.status_code, 200, r.text)
        invoice = r.json()['invoice']
        self.assertEqual(invoice['serial_numbers'], ['934534', '123456'])
        self.assertEqual(invoice['product_items'][0]['quantity'], 2)
        self.assertEqual(invoice['product_items'][1]['extra'], 'keep')
        self.assertEqual(invoice['status'], 'VALIDE')
        self.assertNotEqual(invoice['revision'], original['revision'])
        self.assertEqual(self.put({'expected_revision': original['revision'], 'patient_nom': 'Bob'}).status_code, 409)
        self.assertEqual(self.get()['patient_nom'], 'Alice')

    def test_ambiguity_and_invalid_input_are_atomic(self):
        old = self.get()
        self.assertEqual(self.put({'serial_numbers': ['999999']}).status_code, 400)
        self.assertEqual(self.put({'expected_revision': old['revision'], 'serial_corrections': [
            {'serial_index': 0, 'item_indices': [], 'value': '999999'}]}).status_code, 400)
        self.assertEqual(self.put({'patient_nom': 'X', 'montant_ttc': 'invalid'}).status_code, 400)
        self.assertEqual(self.get(), old)

    def test_collision_does_not_overwrite(self):
        other = self.create('B', 'b.jpg')
        before = self.get()
        response = self.put({'numero_facture': 'B', 'patient_nom': 'Changed'})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.get(), before)
        self.assertEqual(self.db.get_invoice_by_id(other)['numero_facture'], 'B')

    def test_product_line_edit_preserves_metadata(self):
        response = self.put({'product_items': [
            {'product_name': 'A', 'quantity': 4, 'serial_number': '123456'},
            {'product_name': 'B', 'quantity': 1, 'serial_number': '123456'}]})
        # Duplicate serials are ambiguous; names disambiguate only if serial is unique.
        self.assertEqual(response.status_code, 400)
        current = self.get()
        response = self.put({'expected_revision': current['revision'], 'serial_corrections': [
            {'serial_index': 0, 'item_indices': [0], 'value': '999999'}]})
        self.assertEqual(response.status_code, 200)
        response = self.put({'product_items': [
            {'product_name': 'A renamed', 'quantity': 4, 'serial_number': '999999'},
            {'product_name': 'B', 'quantity': 1, 'serial_number': '123456'}]})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()['invoice']['product_items']
        self.assertEqual(items[0]['quantity'], 4)
        self.assertEqual(items[1]['extra'], 'keep')

    def test_legacy_duplicate_and_hash_recalculation(self):
        first = self.get()
        historical = dict(first)
        historical.update(filename='dup.jpg', status='DOUBLON', unique_hash=first['unique_hash'])
        duplicate_id = self.db.save_invoice(historical)
        response = self.put({'patient_nom': 'Alice'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['invoice']['status'], 'DOUBLON')
        response = self.put({'numero_facture': 'C'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['invoice']['unique_hash'], generate_invoice_hash(
            '73282932000074', '2025-01-01', 'C', 120))
        self.assertIn('_dup_', self.db.get_invoice_by_id(duplicate_id)['unique_hash'])

    def test_excel_failure_after_commit(self):
        self.patch_excel.stop()
        with patch.object(web, 'export_to_excel', side_effect=OSError('locked')):
            response = self.put({'patient_nom': 'Alice'})
        self.patch_excel.start()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['warnings'])
        self.assertEqual(self.get()['patient_nom'], 'Alice')

    def test_revalidation_and_excel_warning(self):
        self.excel_mock.return_value = ['Excel indisponible']
        response = self.put({'montant_ttc': 125})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['invoice']['status'], 'ERREUR_CALCUL')
        self.assertEqual(response.json()['warnings'], ['Excel indisponible'])
        self.assertEqual(self.get()['montant_ttc'], 125)


if __name__ == '__main__':
    unittest.main()
