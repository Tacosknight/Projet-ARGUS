import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import web.app as web
from storage.database import InvoiceDatabase


class GroupedCompareTests(unittest.TestCase):
    def test_partial_retry_and_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            database = InvoiceDatabase(str(Path(folder) / 'db.sqlite'))
            calls = []
            failing = {'enabled': True}

            def process(files, invoice_type, prefix, merge_existing, direct_upload_fingerprint):
                calls.append((prefix, len(files), merge_existing))
                if prefix == 'client_1' and failing['enabled']:
                    raise ValueError('unreadable')
                record = {'filename': prefix, 'invoice_type': invoice_type, 'status': 'A_VERIFIER',
                          'serial_numbers': [prefix], 'direct_upload_fingerprint': direct_upload_fingerprint}
                record['id'] = database.save_invoice(record)
                return record

            files = [('vendor_files', ('buy.pdf', b'buy', 'application/pdf')),
                     ('client_0', ('one.jpg', b'one', 'image/jpeg')),
                     ('client_0', ('two.jpg', b'two', 'image/jpeg')),
                     ('client_1', ('sale.pdf', b'sale', 'application/pdf'))]
            with patch.object(web, 'db', database), patch.object(web, 'process_uploaded_invoice_files', side_effect=process), \
                 patch.object(web, 'refresh_excel', return_value=[]), \
                 patch.object(web, 'reconcile_invoices', side_effect=lambda records: {'items': [], 'ids': [r['id'] for r in records]}) as reconcile:
                client = TestClient(web.app)
                first = client.post('/api/compare-grouped', files=files).json()
                self.assertFalse(first['complete'])
                self.assertIsNone(first['reconciliation'])
                self.assertEqual([g['status'] for g in first['groups']], ['enregistré', 'enregistré', 'échec'])
                self.assertEqual(calls[1], ('client_0', 2, False))
                reconcile.assert_not_called()
                failing['enabled'] = False
                second = client.post('/api/compare-grouped', files=files).json()
                self.assertTrue(second['complete'])
                self.assertEqual([g['reused'] for g in second['groups']], [True, True, False])
                self.assertEqual(len(database.get_all_invoices()), 3)
                self.assertEqual(second['reconciliation']['ids'], [g['invoice_id'] for g in second['groups']])

    def test_duplicate_groups_do_not_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            database = InvoiceDatabase(str(Path(folder) / 'db.sqlite'))
            def process(files, invoice_type, prefix, merge_existing, direct_upload_fingerprint):
                record = {'filename': prefix, 'invoice_type': invoice_type, 'status': 'A_VERIFIER',
                          'direct_upload_fingerprint': direct_upload_fingerprint}
                record['id'] = database.save_invoice(record)
                return record
            files = [('vendor_files', ('buy', b'buy')), ('client_0', ('a', b'same')), ('client_1', ('b', b'same'))]
            with patch.object(web, 'db', database), patch.object(web, 'process_uploaded_invoice_files', side_effect=process), patch.object(web, 'refresh_excel', return_value=[]):
                result = TestClient(web.app).post('/api/compare-grouped', files=files).json()
                self.assertFalse(result['complete'])
                self.assertEqual(result['groups'][-1]['status'], 'échec')
                self.assertEqual(len(database.get_all_invoices()), 2)


if __name__ == '__main__':
    unittest.main()
