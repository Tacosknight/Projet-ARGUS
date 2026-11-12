#!/usr/bin/env python3
"""
Tests unitaires pour le moteur de comparaison directe core/comparator.py.
"""

import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.comparator import compare_invoices, compare_serial_numbers, STATUS_MATCH, STATUS_WARNING, STATUS_ERROR


class TestComparator(unittest.TestCase):

    def test_compare_serial_numbers_perfect_match(self):
        v_sn = ["2622X1GMK", "2623X1XYJ"]
        c_sn = ["2622X1GMK", "2623X1XYJ"]
        status, matches, summary = compare_serial_numbers(v_sn, c_sn)
        self.assertEqual(status, STATUS_MATCH)
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(m["status"] == STATUS_MATCH for m in matches))

    def test_compare_serial_numbers_fuzzy_match(self):
        # Patient invoice has OCR noise: 2623X1XY instead of 2623X1XYJ
        v_sn = ["2623X1XYJ"]
        c_sn = ["2623X1XY"]
        status, matches, summary = compare_serial_numbers(v_sn, c_sn)
        self.assertEqual(status, STATUS_WARNING)
        self.assertEqual(matches[0]["status"], STATUS_WARNING)

    def test_compare_serial_numbers_unbilled_device(self):
        # Supplier invoice has 2 devices, patient only refactored 1
        v_sn = ["2622X1GMK", "2623X1XYJ"]
        c_sn = ["2622X1GMK"]
        status, matches, summary = compare_serial_numbers(v_sn, c_sn)
        self.assertEqual(status, STATUS_WARNING)
        waiting_items = [m for m in matches if m["status"] == STATUS_WARNING]
        self.assertEqual(len(waiting_items), 1)
        self.assertEqual(waiting_items[0]["vendor_sn"], "2623X1XYJ")

    def test_compare_invoices_complete_flow(self):
        vendor = {
            "invoice_type": "FOURNISSEUR",
            "fournisseur_nom": "Phonak",
            "numero_facture": "58837130",
            "date_facture": "2026-06-03",
            "serial_numbers": ["2623X1XYJ"],
            "montant_ht": 128.90,
            "montant_tva": 7.09,
            "montant_ttc": 135.99,
        }
        client = {
            "invoice_type": "CLIENT",
            "fournisseur_nom": "Sonova",
            "patient_nom": "Qu'Hen Andre",
            "numero_facture": "194",
            "date_facture": "2026-08-13",
            "serial_numbers": ["2623X1XYJ"],
            "montant_ht": 900.47,
            "montant_tva": 49.53,
            "montant_ttc": 950.00,
        }
        res = compare_invoices(vendor, client)
        self.assertEqual(res["global_status"], STATUS_MATCH)
        self.assertAlmostEqual(res["ecart_ttc"], 814.01, places=2)

        # Check rows contain S/N, TTC, HT, and Bilan
        row_labels = [r["label"] for r in res["rows"]]
        self.assertIn("Numéro(s) de Série (S/N)", row_labels)
        self.assertIn("Montant Total TTC", row_labels)
        self.assertIn("Bilan & Rapprochement", row_labels)

    def test_compare_brand_groups_wsaudiology(self):
        vendor = {
            "fournisseur_nom": "Widex",
            "numero_facture": "301/10109107",
            "serial_numbers": ["208950"],
            "montant_ht": 13.53,
            "montant_ttc": 16.23,
        }
        client = {
            "marque_produit": "Signia",
            "patient_nom": "Martin Jean",
            "numero_facture": "350",
            "serial_numbers": ["208950"],
            "montant_ht": 500.0,
            "montant_ttc": 550.0,
        }
        res = compare_invoices(vendor, client)
        self.assertEqual(res["global_status"], STATUS_MATCH)
        brand_row = next(r for r in res["rows"] if r["label"] == "Marque produit (diagnostic)")
        self.assertEqual(brand_row["status"], STATUS_WARNING)
        self.assertIn("WS Audiology", brand_row["detail"])

    def test_historical_client_brand_is_not_a_product_brand(self):
        result = compare_invoices({'fournisseur_nom': 'Signia'},
                                  {'fournisseur_nom': 'Phoneme', 'invoice_type': 'CLIENT'})
        rows = {row['label']: row for row in result['rows']}
        self.assertEqual(rows['Marque client']['client_val'], 'Phoneme')
        self.assertEqual(rows['Émetteur client']['client_val'], 'Non identifié')
        self.assertEqual(rows['Marque produit (diagnostic)']['status'], STATUS_WARNING)

    def test_compare_patient_dual_match(self):
        vendor = {
            "fournisseur_nom": "Signia",
            "patient_nom": "Beaufils",
            "numero_facture": "301/10340289",
            "serial_numbers": ["934534"],
            "montant_ht": 12.88,
            "montant_ttc": 15.46,
        }
        client = {
            "fournisseur_nom": "Signia",
            "patient_nom": "Beaufils Pierre",
            "numero_facture": "402",
            "serial_numbers": ["934534"],
            "montant_ht": 600.0,
            "montant_ttc": 633.0,
        }
        res = compare_invoices(vendor, client)
        self.assertEqual(res["global_status"], STATUS_MATCH)
        pat_row = next(r for r in res["rows"] if r["label"] == "Patient Bénéficiaire")
        self.assertEqual(pat_row["status"], STATUS_MATCH)
        self.assertIn("Beaufils", pat_row["detail"])


if __name__ == "__main__":
    unittest.main()
