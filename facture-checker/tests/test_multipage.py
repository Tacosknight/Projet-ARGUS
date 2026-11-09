#!/usr/bin/env python3
"""
Tests unitaires et d'intégration pour l'assemblage automatique des factures multi-pages.
"""

import unittest
from pathlib import Path
import sys
import tempfile
import shutil

# Ensure facture-checker is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.multipage import detect_pagination, are_pages_of_same_invoice, consolidate_pages
from core.validator import InvoiceValidator
from core.reconciliation import reconcile_invoices, find_fuzzy_match
from storage.database import InvoiceDatabase


class TestMultiPageAssembly(unittest.TestCase):

    def test_detect_pagination(self):
        text_1 = "PHONAK FRANCE\nFacture N° 58837130\n1/2\n"
        cur, tot = detect_pagination(text_1)
        self.assertEqual(cur, 1)
        self.assertEqual(tot, 2)

        text_2 = "Total Hors taxes : 1 067,39 €\nMontant T.T.C. : 1 129,25 €\n2/2"
        cur, tot = detect_pagination(text_2)
        self.assertEqual(cur, 2)
        self.assertEqual(tot, 2)

        text_single = "Facture 12345\nPage 1 sur 1\nTotal: 100 €"
        cur, tot = detect_pagination(text_single)
        self.assertEqual(cur, 1)
        self.assertEqual(tot, 1)

    def test_are_pages_of_same_invoice(self):
        doc_a = {
            "numero_facture": "58837130",
            "page_current": 1,
            "page_total": 2,
            "fournisseur_nom": "Phonak",
            "invoice_type": "FOURNISSEUR",
        }
        doc_b = {
            "numero_facture": "58837130",
            "page_current": 2,
            "page_total": 2,
            "fournisseur_nom": "Phonak",
            "invoice_type": "FOURNISSEUR",
        }
        self.assertTrue(are_pages_of_same_invoice(doc_a, doc_b))

        # Test complementary pagination without matching invoice number
        doc_c = {
            "numero_facture": None,
            "page_current": 1,
            "page_total": 2,
            "fournisseur_nom": "Phonak",
            "invoice_type": "FOURNISSEUR",
            "raw_text": "Phoneme Audition Coulaines Phonak",
        }
        doc_d = {
            "numero_facture": None,
            "page_current": 2,
            "page_total": 2,
            "fournisseur_nom": "Phonak",
            "invoice_type": "FOURNISSEUR",
            "raw_text": "Phoneme Audition Coulaines Phonak",
        }
        self.assertTrue(are_pages_of_same_invoice(doc_c, doc_d))

        # Different suppliers should not match
        doc_e = {
            "numero_facture": None,
            "page_current": 2,
            "page_total": 2,
            "fournisseur_nom": "Oticon",
            "invoice_type": "FOURNISSEUR",
            "raw_text": "Oticon",
        }
        self.assertFalse(are_pages_of_same_invoice(doc_c, doc_e))

    def test_consolidate_pages(self):
        page_1 = {
            "filename": "scan_p1.jpg",
            "invoice_type": "FOURNISSEUR",
            "numero_facture": "58837130",
            "date_facture": "2026-06-03",
            "fournisseur_nom": "Phonak",
            "montant_ht": 257.80,
            "montant_tva": 14.18,
            "montant_ttc": 271.98,
            "serial_numbers": ["2623X1XVY", "2623X1XYJ"],
            "page_current": 1,
            "page_total": 2,
            "raw_text": "Page 1 text with SN:(2623X1XVY)",
        }
        page_2 = {
            "filename": "scan_p2.jpg",
            "invoice_type": "FOURNISSEUR",
            "numero_facture": "58837130",
            "date_facture": "2026-06-03",
            "fournisseur_nom": "Phonak",
            "montant_ht": 1067.39,
            "montant_tva": 61.86,
            "montant_ttc": 1129.25,
            "serial_numbers": ["2626X07MU", "2626X07MV", "2619F10YE5"],
            "page_current": 2,
            "page_total": 2,
            "raw_text": "Page 2 text with SN:(2626X07MU,2626X07MV)",
        }

        consolidated = consolidate_pages([page_1, page_2])

        self.assertTrue(consolidated["is_multipage"])
        self.assertEqual(consolidated["pages_count"], 2)
        self.assertEqual(consolidated["numero_facture"], "58837130")
        self.assertEqual(consolidated["fournisseur_nom"], "Phonak")

        # Serial numbers must contain all 5
        self.assertEqual(
            consolidated["serial_numbers"],
            ["2619F10YE5", "2623X1XVY", "2623X1XYJ", "2626X07MU", "2626X07MV"]
        )

        # Totals must be from authoritative final page
        self.assertEqual(consolidated["montant_ht"], 1067.39)
        self.assertEqual(consolidated["montant_ttc"], 1129.25)

        # Validator check: Should be VALIDE without SIRET errors
        validator = InvoiceValidator()
        status, errors, _ = validator.validate(consolidated)
        self.assertEqual(status, "VALIDE")
        self.assertNotIn("SIRET_INVALIDE", [e for e in errors])

    def test_reconciliation_with_fuzzy_sn(self):
        # Patient invoice has OCR noise: 2623X1XY) instead of 2623X1XYJ
        supplier_doc = {
            "id": 1,
            "filename": "phonak_consolidated.jpg",
            "invoice_type": "FOURNISSEUR",
            "montant_ttc": 1129.25,
            "serial_numbers": ["2619F10YE5", "2623X1XVY", "2623X1XYJ", "2626X07MU", "2626X07MV"],
        }
        client_doc = {
            "id": 2,
            "filename": "phoneme_patient.jpg",
            "invoice_type": "CLIENT",
            "montant_ttc": 1900.00,
            "serial_numbers": ["2622X1GMK", "2623X1XY"],
        }

        # Check fuzzy matching helper
        match = find_fuzzy_match("2623X1XYJ", ["2622X1GMK", "2623X1XY"])
        self.assertEqual(match, "2623X1XY")

        reconcil = reconcile_invoices([supplier_doc, client_doc])
        kpi = reconcil["kpi"]
        self.assertGreaterEqual(kpi["rapproches_count"], 1)

        # Find 2623X1XYJ in items
        item = next(it for it in reconcil["items"] if it["serial_number"] == "2623X1XYJ")
        self.assertEqual(item["status"], "RAPPROCHE_PROBABLE")


if __name__ == "__main__":
    unittest.main()
