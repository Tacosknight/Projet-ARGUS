#!/usr/bin/env python3
"""
Test d'intégration de bout en bout avec les vraies images fournies par l'utilisateur :
- Page 1/2 Fournisseur Phonak
- Page 2/2 Fournisseur Phonak (totaux et S/N complémentaires)
- Facture Client Phonème Audition
"""

import unittest
from pathlib import Path
import sys
import tempfile
import shutil
import os

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from starlette.testclient import TestClient
import web.app as web_app
from storage.database import InvoiceDatabase
from core.ocr_engine import OCREngine

ARTIFACTS_DIR = Path(os.environ.get("ARGUS_OCR_SAMPLES_DIR", str(Path(__file__).parent / "samples")))
IMG_PAGE1 = ARTIFACTS_DIR / "media_1793635368763_34d55d6a.jpg"
IMG_PAGE2 = ARTIFACTS_DIR / "media_1793635368777_1aec294b.jpg"
IMG_PATIENT = ARTIFACTS_DIR / "media_1793635368783_5eab80b2.jpg"


@unittest.skipUnless(
    os.environ.get("ARGUS_RUN_REAL_OCR_TESTS") == "1"
    and IMG_PAGE1.exists() and IMG_PAGE2.exists() and IMG_PATIENT.exists(),
    "Test OCR réel optionnel : définir ARGUS_RUN_REAL_OCR_TESTS=1 avec les échantillons locaux",
)
class TestEndToEndRealInvoices(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_invoices.db"
        self.excel_path = Path(self.temp_dir) / "test_synthese.xlsx"
        self.input_dir = Path(self.temp_dir) / "test_input_photos"
        self.input_dir.mkdir(parents=True, exist_ok=True)

        # Inject isolated database and paths into web_app
        self.test_db = InvoiceDatabase(str(self.db_path))
        web_app.db = self.test_db
        web_app.DB_PATH = self.db_path
        web_app.EXCEL_PATH = self.excel_path
        web_app.INPUT_DIR = self.input_dir

        self.client = TestClient(web_app.app)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_simultaneous_multipage_upload(self):
        """Vérifie l'upload simultané de Page 1 + Page 2 sur /api/scan."""
        self.assertTrue(IMG_PAGE1.exists(), f"Image manquante: {IMG_PAGE1}")
        self.assertTrue(IMG_PAGE2.exists(), f"Image manquante: {IMG_PAGE2}")

        with open(IMG_PAGE1, "rb") as f1, open(IMG_PAGE2, "rb") as f2:
            response = self.client.post(
                "/api/scan",
                files=[
                    ("files", ("page1.jpg", f1, "image/jpeg")),
                    ("files", ("page2.jpg", f2, "image/jpeg")),
                ],
                data={"invoice_type": "FOURNISSEUR"}
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        # 1. Validation du statut
        self.assertEqual(data.get("status"), "VALIDE")
        self.assertTrue(data.get("is_multipage"))
        self.assertEqual(data.get("pages_count"), 2)

        # 2. Vérification des montants consolidés (issus de la page 2 certifiée)
        self.assertAlmostEqual(data.get("montant_ht"), 1067.39, places=2)
        self.assertAlmostEqual(data.get("montant_ttc"), 1129.25, places=2)

        # 3. Vérification des 5 numéros de série fusionnés
        serials = data.get("serial_numbers", [])
        expected_subset = {"2623X1XVY", "2623X1XYJ", "2626X07MU", "2626X07MV"}
        self.assertTrue(expected_subset.issubset(set(serials)), f"S/N manquants dans: {serials}")

        # 4. Vérification base SQLite : doit contenir 1 seule facture consolidée
        db_records = self.test_db.get_all_invoices()
        self.assertEqual(len(db_records), 1)
        self.assertEqual(db_records[0]["montant_ttc"], 1129.25)

    def test_sequential_multipage_and_reconciliation(self):
        """
        Vérifie l'assemblage automatique séquentiel :
        1. Scan Page 1 seule -> Sauvegarde en BDD
        2. Scan Page 2 seule -> Détection de la Page 1, fusion automatique, remplacement en BDD
        3. Scan Facture Patient -> Rapprochement S/N avec la facture consolidée
        """
        # Étape 1 : Page 1 seule
        with open(IMG_PAGE1, "rb") as f1:
            resp1 = self.client.post(
                "/api/scan",
                files=[("files", ("page1.jpg", f1, "image/jpeg"))],
                data={"invoice_type": "FOURNISSEUR"}
            )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(len(self.test_db.get_all_invoices()), 1)

        # Étape 2 : Page 2 seule (doit consolider avec Page 1 en BDD)
        with open(IMG_PAGE2, "rb") as f2:
            resp2 = self.client.post(
                "/api/scan",
                files=[("files", ("page2.jpg", f2, "image/jpeg"))],
                data={"invoice_type": "FOURNISSEUR"}
            )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()

        self.assertTrue(data2.get("is_multipage"))
        self.assertEqual(data2.get("status"), "VALIDE")
        self.assertAlmostEqual(data2.get("montant_ttc"), 1129.25, places=2)

        # La base doit toujours avoir 1 seule facture fournisseur unifiée
        invoices_after_step2 = self.test_db.get_all_invoices()
        self.assertEqual(len(invoices_after_step2), 1)

        # Étape 3 : Facture Client Patient
        with open(IMG_PATIENT, "rb") as fp:
            resp3 = self.client.post(
                "/api/scan",
                files=[("files", ("patient.jpg", fp, "image/jpeg"))],
                data={"invoice_type": "CLIENT"}
            )
        self.assertEqual(resp3.status_code, 200)

        # Vérification du rapprochement global
        rec_resp = self.client.get("/api/reconciliation")
        self.assertEqual(rec_resp.status_code, 200)
        rec_data = rec_resp.json()

        kpi = rec_data.get("kpi", {})
        self.assertGreaterEqual(kpi.get("rapproches_count", 0), 1)

        # Vérification du S/N rapproché
        items = rec_data.get("items", [])
        matched_items = [it for it in items if it.get("status") == "RAPPROCHE"]
        self.assertGreaterEqual(len(matched_items), 1)


if __name__ == "__main__":
    unittest.main()
