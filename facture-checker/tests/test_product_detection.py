#!/usr/bin/env python3
"""
Tests unitaires pour la détection, l'extraction, la liaison S/N et la comparaison
des noms de produits et modèles d'appareils auditifs.
"""

import unittest
from pathlib import Path
import sys
import tempfile
import os

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.parser import InvoiceParser, clean_product_name
from core.multipage import consolidate_pages
from core.comparator import (
    compare_product_names,
    normalize_product_for_matching,
    compare_invoices,
    STATUS_MATCH,
    STATUS_WARNING,
    STATUS_ERROR,
)
from core.reconciliation import reconcile_invoices
from storage.database import InvoiceDatabase
from storage.export_excel import export_to_excel


def make_boxes(text: str):
    return [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]


class TestProductDetection(unittest.TestCase):

    def test_clean_product_name(self):
        """Vérifie le nettoyage des suffixes parasites de tableaux (prix, TVA, etc.)."""
        raw1 = "Audéo L30-312 Sand Beige 1 28,00 5,50%"
        self.assertEqual(clean_product_name(raw1), "Audéo L30-312 Sand Beige")

        raw2 = "Widex Moment 440 mRIC R D 1 PCS 5.5% 32,00"
        self.assertEqual(clean_product_name(raw2), "Widex Moment 440 mRIC R D")

        raw3 = "DMSM RIC résine rosé 1 Pce"
        self.assertEqual(clean_product_name(raw3), "DMSM RIC résine rosé")

    def test_normalize_product_for_matching(self):
        """Vérifie que les marques et tirets sont normalisés pour comparaison."""
        self.assertEqual(normalize_product_for_matching("Phonak Audéo L30-312"), "audeol30312")
        self.assertEqual(normalize_product_for_matching("Audéo L30 312"), "audeol30312")
        self.assertEqual(normalize_product_for_matching("Signia Pure Charge&Go 7AX"), "purechargego7ax")

    def test_extract_phonak_product_with_serial(self):
        """Extraction d'un produit Phonak avec son numéro de série."""
        text = """
        SONOVA FRANCE SAS
        Facture N° 58837130
        Date : 03/06/2026
        Désignation
        Phonak Audéo L30-312 Sand Beige
        N° Série : 2422X1GMK
        Montant HT : 128.90 €
        TVA 5.5% : 7.09 €
        Total TTC : 135.99 €
        """
        parser = InvoiceParser(make_boxes(text), forced_type="FOURNISSEUR")
        result = parser.parse()

        self.assertIn("2422X1GMK", result["serial_numbers"])
        self.assertTrue(len(result["product_names"]) >= 1)
        # Vérifie qu'un nom de modèle Phonak Audéo a été capturé
        self.assertTrue(any("Audéo L30-312" in p for p in result["product_names"]))

        # Vérifie que l'item lie le S/N au produit
        items = result.get("product_items", [])
        matched_items = [it for it in items if it.get("serial_number") == "2422X1GMK"]
        self.assertTrue(len(matched_items) >= 1)
        self.assertTrue("Audéo L30-312" in matched_items[0]["product_name"])

    def test_extract_widex_product(self):
        """Extraction d'un produit Widex Moment."""
        text = """
        WSAUDIOLOGY FRANCE
        Facture : 301/10109107
        Widex Moment 440 mRIC R D Tech Black
        S/N : 934534
        Total TTC : 1129,25 €
        """
        parser = InvoiceParser(make_boxes(text), forced_type="FOURNISSEUR")
        result = parser.parse()

        self.assertIn("934534", result["serial_numbers"])
        self.assertTrue(any("Moment 440" in p for p in result["product_names"]))

    def test_extract_custom_earmold_atelier_embout(self):
        """Extraction d'un embout sur-mesure Atelier de l'Embout."""
        text = """
        L'ATELIER DE L'EMBOUT
        Facture N° 45892
        DMSM RIC résine rosé
        N° Série : 934564
        Total TTC : 85,00 €
        """
        parser = InvoiceParser(make_boxes(text), forced_type="FOURNISSEUR")
        result = parser.parse()

        self.assertIn("934564", result["serial_numbers"])
        self.assertTrue(any("DMSM RIC" in p for p in result["product_names"]))

    def test_extract_client_phoneme_invoice(self):
        """Extraction de produits depuis une facture de vente patient Phonème."""
        text = """
        PHONEME CENTRE AUDITIF
        Facture N° 194
        Date : 13/08/2026
        Patient : M. Beaufils Pierre
        Prestation d'appareillage auditif :
        1 Phonak Audéo L30-312 Sand Beige - S/N : 2422X1GMK
        Total TTC : 950,00 €
        """
        parser = InvoiceParser(make_boxes(text), forced_type="CLIENT")
        result = parser.parse()

        self.assertIn("2422X1GMK", result["serial_numbers"])
        self.assertTrue(any("Audéo L30-312" in p for p in result["product_names"]))

    def test_multipage_product_consolidation(self):
        """Consolidation multi-pages des produits sans duplication."""
        page1 = {
            "id": 1,
            "invoice_type": "FOURNISSEUR",
            "numero_facture": "F100",
            "serial_numbers": ["2422X1GMK"],
            "product_names": ["Phonak Audéo L30-312"],
            "product_items": [{"product_name": "Phonak Audéo L30-312", "serial_number": "2422X1GMK"}],
            "montant_ttc": 135.99,
        }
        page2 = {
            "id": 2,
            "invoice_type": "FOURNISSEUR",
            "numero_facture": "F100",
            "serial_numbers": ["2423X1XYJ"],
            "product_names": ["Phonak Audéo L30-312", "Charger Combi BTE"],
            "product_items": [
                {"product_name": "Phonak Audéo L30-312", "serial_number": "2423X1XYJ"},
                {"product_name": "Charger Combi BTE", "serial_number": None},
            ],
            "montant_ttc": 135.99,
        }
        consolidated = consolidate_pages([page1, page2])
        self.assertEqual(len(consolidated["serial_numbers"]), 2)
        # Doit contenir Audéo L30-312 et Charger Combi BTE une seule fois
        self.assertEqual(len(consolidated["product_names"]), 2)
        self.assertIn("Phonak Audéo L30-312", consolidated["product_names"])
        self.assertIn("Charger Combi BTE", consolidated["product_names"])

    def test_compare_products_match_and_mismatch(self):
        """Vérifie la comparaison de produits entre achat et vente."""
        # 1. Concordance exacte ou quasi-exacte
        status, detail = compare_product_names(
            ["Phonak Audéo L30-312"],
            ["Audéo L30 312 Sand Beige"],
        )
        self.assertEqual(status, STATUS_MATCH)

        # 2. Divergence manifeste de produit
        status_err, detail_err = compare_product_names(
            ["Widex Moment 440 mRIC"],
            ["Signia Pure Charge&Go 7AX"],
        )
        self.assertEqual(status_err, STATUS_ERROR)

    def test_compare_invoices_product_row(self):
        """Vérifie que compare_invoices produit la ligne Appareil(s) / Modèle(s)."""
        vendor = {
            "invoice_type": "FOURNISSEUR",
            "fournisseur_nom": "Phonak",
            "numero_facture": "58837130",
            "date_facture": "2026-06-03",
            "serial_numbers": ["2422X1GMK"],
            "product_names": ["Phonak Audéo L30-312"],
            "product_items": [{"product_name": "Phonak Audéo L30-312", "serial_number": "2422X1GMK"}],
            "montant_ht": 128.90,
            "montant_tva": 7.09,
            "montant_ttc": 135.99,
        }
        client = {
            "invoice_type": "CLIENT",
            "fournisseur_nom": "Phonak",
            "patient_nom": "Beaufils Pierre",
            "numero_facture": "194",
            "date_facture": "2026-08-13",
            "serial_numbers": ["2422X1GMK"],
            "product_names": ["Audéo L30 312"],
            "product_items": [{"product_name": "Audéo L30 312", "serial_number": "2422X1GMK"}],
            "montant_ht": 900.47,
            "montant_tva": 49.53,
            "montant_ttc": 950.00,
        }

        res = compare_invoices(vendor, client)
        self.assertEqual(res["bilan_status"], STATUS_MATCH)

        # Vérifie la présence de la ligne produits
        prod_row = next((r for r in res["rows"] if r["category"] == "products"), None)
        self.assertIsNotNone(prod_row)
        self.assertEqual(prod_row["label"], "Appareil(s) / Modèle(s)")
        self.assertEqual(prod_row["status"], STATUS_MATCH)

    def test_database_persistence_and_update(self):
        """Vérifie la persistance SQLite et l'édition de product_names."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            db = InvoiceDatabase(db_path=db_path)
            db.init_db()

            inv_data = {
                "filename": "test_inv.jpg",
                "invoice_type": "FOURNISSEUR",
                "numero_facture": "F-2026-99",
                "date_facture": "2026-05-10",
                "fournisseur_nom": "Signia",
                "serial_numbers": ["12345678"],
                "product_names": ["Signia Pure Charge&Go 7AX", "Chargeur Standard"],
                "montant_ht": 500.0,
                "montant_tva": 27.5,
                "montant_ttc": 527.5,
                "status": "VALIDE",
                "unique_hash": "hash_test_product_123",
            }
            inv_id = db.save_invoice(inv_data)
            self.assertTrue(inv_id > 0)

            # Lecture
            fetched = db.get_invoice_by_id(inv_id)
            self.assertIsNotNone(fetched)
            self.assertIsInstance(fetched["product_names"], list)
            self.assertEqual(len(fetched["product_names"]), 2)
            self.assertIn("Signia Pure Charge&Go 7AX", fetched["product_names"])

            # Modification
            updated = db.update_invoice(inv_id, {"product_names": ["Signia Pure Charge&Go 7AX"]})
            self.assertTrue(updated)

            fetched_after = db.get_invoice_by_id(inv_id)
            self.assertEqual(len(fetched_after["product_names"]), 1)
            self.assertEqual(fetched_after["product_names"][0], "Signia Pure Charge&Go 7AX")
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_reconciliation_and_excel_export_with_products(self):
        """Vérifie que la réconciliation et l'export Excel intègrent les modèles de produits."""
        invoices = [
            {
                "id": 1,
                "invoice_type": "FOURNISSEUR",
                "fournisseur_nom": "Phonak",
                "numero_facture": "FAC-ACHAT-1",
                "date_facture": "2026-01-10",
                "serial_numbers": ["SN-AUD-01"],
                "product_names": ["Phonak Audéo L30-312"],
                "product_items": [{"product_name": "Phonak Audéo L30-312", "serial_number": "SN-AUD-01"}],
                "montant_ht": 100.0,
                "montant_tva": 5.5,
                "montant_ttc": 105.5,
                "status": "VALIDE",
                "filename": "achat.pdf",
            },
            {
                "id": 2,
                "invoice_type": "CLIENT",
                "fournisseur_nom": "Phonak",
                "patient_nom": "Dupont Jean",
                "numero_facture": "FAC-VENTE-1",
                "date_facture": "2026-02-15",
                "serial_numbers": ["SN-AUD-01"],
                "product_names": ["Audéo L30-312"],
                "product_items": [{"product_name": "Audéo L30-312", "serial_number": "SN-AUD-01"}],
                "montant_ht": 900.0,
                "montant_tva": 49.5,
                "montant_ttc": 949.5,
                "status": "VALIDE",
                "filename": "vente.pdf",
            },
        ]

        # Réconciliation
        rec = reconcile_invoices(invoices)
        items = rec["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "RAPPROCHE")
        self.assertEqual(items[0]["produit_nom"], "Phonak Audéo L30-312")

        # Export Excel
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            excel_path = tf.name

        try:
            res_path = export_to_excel(invoices, output_path=excel_path)
            self.assertTrue(os.path.exists(res_path))
            self.assertTrue(os.path.getsize(res_path) > 1000)
        finally:
            if os.path.exists(excel_path):
                os.remove(excel_path)


if __name__ == "__main__":
    unittest.main()
