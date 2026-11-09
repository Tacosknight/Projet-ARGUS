import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from storage.database import InvoiceDatabase
from web.app import app


class DocumentPreviewTests(unittest.TestCase):
    def test_original_and_missing_document(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = InvoiceDatabase(str(root / 'test.db'))
            (root / 'stored.pdf').write_bytes(b'%PDF-1.4\n')
            invoice_id = database.save_invoice({
                'filename': 'rendered.jpg', 'status': 'A_VERIFIER',
                'source_documents': [{'filename': 'stored.pdf', 'original_name': 'Facture été.pdf'}],
            })
            with patch('web.app.db', database), patch('web.app.INPUT_DIR', root):
                client = TestClient(app)
                self.assertEqual(client.get('/api/invoices').json()[0]['source_documents'][0]['original_name'], 'Facture été.pdf')
                response = client.get(f'/api/invoices/{invoice_id}/documents/0')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'%PDF-1.4\n')
                self.assertTrue(response.headers['content-disposition'].startswith('inline;'))
                self.assertEqual(client.get(f'/api/invoices/{invoice_id}/documents/1').status_code, 404)

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            database = InvoiceDatabase(str(Path(folder) / 'test.db'))
            invoice_id = database.save_invoice({'filename': '../secret.pdf', 'status': 'A_VERIFIER'})
            with patch('web.app.db', database), patch('web.app.INPUT_DIR', Path(folder)):
                response = TestClient(app).get(f'/api/invoices/{invoice_id}/documents/0')
                self.assertEqual(response.status_code, 404)
