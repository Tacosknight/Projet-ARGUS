"""Vérification du choix de source PDF au niveau de l'API, sans modèle OCR."""
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

_app_data = tempfile.TemporaryDirectory()
os.environ['ARGUS_DATA_DIR'] = _app_data.name
from web import app as web
from core.validator import InvoiceValidator
from storage.database import InvoiceDatabase


class HybridWebTests(unittest.TestCase):
    def test_mixed_pdf_and_extraction_failure_use_ocr_only_when_needed(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            db = InvoiceDatabase(str(root / 'test.db'))
            stack.enter_context(patch.object(web, 'db', db))
            stack.enter_context(patch.object(web, 'INPUT_DIR', root))
            stack.enter_context(patch.object(web, 'validator', InvoiceValidator(db_is_duplicate_fn=db.is_hash_exists)))
            stack.enter_context(patch.object(web, 'refresh_excel', return_value=[]))
            img = np.zeros((20, 20, 3), dtype=np.uint8)
            stack.enter_context(patch.object(web, 'iter_document_pages', return_value=[(1, 3, img), (2, 3, img), (3, 3, img)]))
            native = [{'text': 'FACTURE', 'box': [[0,0],[10,0],[10,10],[0,10]], 'confidence': 1}]
            stack.enter_context(patch.object(web, 'native_pdf_page', side_effect=[(native, 'native_pdf'), (None, 'scan'), RuntimeError('unavailable')]))
            preprocess = stack.enter_context(patch.object(web, 'preprocess_image', return_value=img))
            ocr = stack.enter_context(patch.object(web.ocr_engine, 'extract_text_and_boxes', return_value=[]))
            response = TestClient(web.app).post('/api/scan', files={'file': ('invoice.pdf', b'pdf', 'application/pdf')})
            self.assertEqual(response.status_code, 200, response.text)
            pages = response.json()['extraction_pages']
            self.assertEqual([p['source'] for p in pages], ['pdf_text', 'ocr', 'ocr'])
            self.assertEqual([p['text_detected'] for p in pages], [True, False, False])
            self.assertEqual(ocr.call_count, 2)
            self.assertEqual(preprocess.call_count, 2)
            self.assertEqual(len(list(root.glob('*.jpg'))), 3)


if __name__ == '__main__':
    unittest.main()
