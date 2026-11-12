import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import web.app as web
from storage.database import InvoiceDatabase
from core.reconciliation import grouped_client_totals
from core.multipage import consolidate_pages


class GroupedCompareTests(unittest.TestCase):
    def test_document_totals_and_multipage(self):
        page = lambda n, **kw: dict(invoice_type='CLIENT', page_current=n, page_total=2, **kw)
        client = consolidate_pages([page(1, montant_ht=20), page(2, montant_ttc=42.10)])
        ambiguous = consolidate_pages([page(1, montant_ht=100, montant_ttc=120), page(2, montant_ttc=42.10)])
        self.assertIsNone(ambiguous['montant_ttc'])
        client.update(id=1, product_items=[{'serial_number': 'A'}, {'serial_number': 'B'}])
        missing = consolidate_pages([page(1, montant_ht=50), page(2, montant_ht=40)])
        missing['id'] = 2
        result = grouped_client_totals([client, client, missing,
            {'id': 3, 'invoice_type': 'CLIENT', 'montant_ttc': 0},
            {'id': 4, 'invoice_type': 'CLIENT', 'document_type': 'AVOIR', 'montant_ttc': 100},
            {'id': 5, 'invoice_type': 'FOURNISSEUR', 'montant_ttc': 500}])
        self.assertEqual(result['nombre_factures'], 3)
        self.assertEqual(result['total_connu_ttc'], 42.10)
        self.assertEqual(result['montants_manquants'], 1)
        self.assertFalse(result['complet'])
        self.assertIsNone(missing['montant_ttc'])
        self.assertEqual(grouped_client_totals([client])['complet'], True)

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
                          'serial_numbers': [prefix], 'montant_ttc': 12.30 if invoice_type == 'CLIENT' else 100,
                          'direct_upload_fingerprint': direct_upload_fingerprint}
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
                self.assertIsNone(first['totaux_clients'])
                self.assertEqual([g['status'] for g in first['groups']], ['enregistré', 'enregistré', 'échec'])
                self.assertEqual(calls[1], ('client_0', 2, False))
                reconcile.assert_not_called()
                failing['enabled'] = False
                second = client.post('/api/compare-grouped', files=files).json()
                self.assertTrue(second['complete'])
                self.assertEqual([g['reused'] for g in second['groups']], [True, True, False])
                self.assertEqual(len(database.get_all_invoices()), 3)
                self.assertEqual(second['reconciliation']['ids'], [g['invoice_id'] for g in second['groups']])
                self.assertEqual(second['totaux_clients']['total_connu_ttc'], 24.60)
                self.assertTrue(second['totaux_clients']['complet'])

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
