#!/usr/bin/env python3
"""
Tests unitaires pour l'édition interactive Human-in-the-Loop (GET / PUT /api/invoices/{id}).
"""

import unittest
from pathlib import Path
import sys
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web.app import app, db


class TestApiEditInvoice(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        # Création d'une facture de test
        self.inv_id = db.save_invoice({
            "filename": "test_edit.jpg",
            "invoice_type": "FOURNISSEUR",
            "numero_facture": "INIT-001",
            "date_facture": "2025-01-01",
            "montant_ht": 100.0,
            "montant_tva": 20.0,
            "montant_ttc": 120.0,
            "fournisseur_nom": "Phonak",
            "patient_nom": "Test Patient",
            "serial_numbers": ["111222"],
            "status": "A_VERIFIER",
            "unique_hash": "test_hash_edit_12345",
        })

    def tearDown(self):
        # Nettoyage
        if self.inv_id:
            db.delete_invoice(self.inv_id)

    def test_get_single_invoice(self):
        res = self.client.get(f"/api/invoices/{self.inv_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["id"], self.inv_id)
        self.assertEqual(data["numero_facture"], "INIT-001")
        self.assertIn("111222", data["serial_numbers"])

    def test_put_update_invoice(self):
        updates = {
            "numero_facture": "UPDATED-999",
            "date_facture": "2025-06-15",
            "montant_ht": 200.0,
            "montant_ttc": 211.0,
            "fournisseur_nom": "Widex",
            "serial_numbers": "934 534, 934564",  # Doit être nettoyé en ['934534', '934564']
        }
        res = self.client.put(f"/api/invoices/{self.inv_id}", json=updates)
        self.assertEqual(res.status_code, 200)
        resp_data = res.json()
        self.assertEqual(resp_data["status"], "OK")

        # Vérification des données mises à jour
        inv = resp_data["invoice"]
        self.assertEqual(inv["numero_facture"], "UPDATED-999")
        self.assertEqual(inv["date_facture"], "2025-06-15")
        self.assertAlmostEqual(inv["montant_ht"], 200.0, places=2)
        self.assertAlmostEqual(inv["montant_ttc"], 211.0, places=2)
        self.assertAlmostEqual(inv["montant_tva"], 11.0, places=2)  # Calcul auto 211 - 200
        self.assertEqual(inv["fournisseur_nom"], "Widex")
        self.assertIn("934534", inv["serial_numbers"])
        self.assertIn("934564", inv["serial_numbers"])


if __name__ == "__main__":
    unittest.main()
