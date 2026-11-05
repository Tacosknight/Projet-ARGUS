#!/usr/bin/env python3
"""
Tests unitaires pour le correcteur heuristique post-OCR (core/post_corrector.py).
"""

import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.post_corrector import (
    clean_serial_number,
    normalize_amount_text,
    normalize_fiscal_tokens,
    clean_vendor_fuzzy,
    post_correct_ocr_boxes,
)


class TestPostCorrector(unittest.TestCase):

    def test_clean_serial_numbers_with_spaces(self):
        # Espaces erronés insérés par OCR au milieu des chiffres
        self.assertEqual(clean_serial_number("934 534"), "934534")
        self.assertEqual(clean_serial_number("241 089 23"), "24108923")
        self.assertEqual(clean_serial_number(" 208 950 "), "208950")

    def test_clean_serial_numbers_with_ocr_letter_confusions(self):
        # 'O' ou 'o' pris pour '0'
        self.assertEqual(clean_serial_number("241O8923"), "24108923")
        self.assertEqual(clean_serial_number("934o54"), "934054")
        # 'l' ou 'I' pris pour '1'
        self.assertEqual(clean_serial_number("24l08923"), "24108923")
        self.assertEqual(clean_serial_number("24I08923"), "24108923")
        # 'S' pris pour '5'
        self.assertEqual(clean_serial_number("934S64"), "934564")
        # 'B' pris pour '8'
        self.assertEqual(clean_serial_number("2410B923"), "24108923")

    def test_clean_serial_numbers_ear_mold_preservation(self):
        # L'Atelier de l'Embout : 250618GUAN1 ne doit pas être altéré sur les lettres GUAN
        self.assertEqual(clean_serial_number("250618GUAN1"), "250618GUAN1")
        self.assertEqual(clean_serial_number("250618guan2"), "250618GUAN2")

    def test_normalize_amount_text(self):
        # Espaces entre entiers et centimes
        self.assertEqual(normalize_amount_text("1 129 00 EUR"), "1 129,00 EUR")
        self.assertEqual(normalize_amount_text("414 00"), "414,00")
        self.assertEqual(normalize_amount_text("Total TTC 1129 00 €"), "Total TTC 1129,00 €")
        # Double virgule
        self.assertEqual(normalize_amount_text("1129,,00"), "1129,00")

    def test_normalize_fiscal_tokens(self):
        self.assertEqual(normalize_fiscal_tokens("TOTAL T.TC"), "Total T.T.C.")
        self.assertEqual(normalize_fiscal_tokens("Montant HT"), "Total H.T.")
        self.assertEqual(normalize_fiscal_tokens("T.V.A 20%"), "TVA 20%")

    def test_clean_vendor_fuzzy(self):
        self.assertEqual(clean_vendor_fuzzy("Pbonak"), "Phonak")
        self.assertEqual(clean_vendor_fuzzy("Wldex SAS"), "Widex")
        self.assertEqual(clean_vendor_fuzzy("Signia France"), "Signia")
        self.assertEqual(clean_vendor_fuzzy("Atelier de l'embout"), "L'Atelier de l'Embout")

    def test_post_correct_ocr_boxes(self):
        boxes = [
            {"text": "Total H.T 414 00 EUR", "confidence": 0.95},
            {"text": "Total T.TC 1129 00", "confidence": 0.92},
        ]
        corrected = post_correct_ocr_boxes(boxes)
        self.assertEqual(len(corrected), 2)
        self.assertIn("Total H.T. 414,00 EUR", corrected[0]["text"])
        self.assertIn("Total T.T.C. 1129,00", corrected[1]["text"])


if __name__ == "__main__":
    unittest.main()
