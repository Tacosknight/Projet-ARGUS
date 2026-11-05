#!/usr/bin/env python3
"""
Tests unitaires dédiés pour le filtrage strict des faux positifs de numéros de série (S/N) :
- Éradication des numéros de téléphone (fixes, mobiles, spéciaux, internationaux, avec/sans séparateurs).
- Éradication des coordonnées (fax, email, contact, standard).
- Éradication des dates compactes, codes postaux, SIREN/SIRET, numéros de factures et clients.
- Préservation à 100% des vrais numéros de série de tous les fabricants d'audioprothèses.
"""

import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.post_corrector import is_phone_number, is_compact_date, clean_serial_number
from core.parser import InvoiceParser


class TestPhoneNumberDetection(unittest.TestCase):
    """Vérification unitaire de la détection de tous les formats téléphoniques."""

    def test_french_landline_formats(self):
        # Format 02 (Pays de la Loire / Sarthe / etc.)
        self.assertTrue(is_phone_number("02 43 28 15 10"))
        self.assertTrue(is_phone_number("02.43.28.15.10"))
        self.assertTrue(is_phone_number("02-43-28-15-10"))
        self.assertTrue(is_phone_number("0243281510"))
        # Format 01 (Île-de-France)
        self.assertTrue(is_phone_number("01 42 89 10 12"))
        self.assertTrue(is_phone_number("01.42.89.10.12"))
        self.assertTrue(is_phone_number("01-42-89-10-12"))
        self.assertTrue(is_phone_number("0142891012"))
        # Format 03, 04, 05
        self.assertTrue(is_phone_number("03 20 12 34 56"))
        self.assertTrue(is_phone_number("04 91 23 45 67"))
        self.assertTrue(is_phone_number("05 56 34 56 78"))

    def test_french_mobile_and_special_formats(self):
        # 06 et 07 (mobiles)
        self.assertTrue(is_phone_number("06 12 34 56 78"))
        self.assertTrue(is_phone_number("06.12.34.56.78"))
        self.assertTrue(is_phone_number("0612345678"))
        self.assertTrue(is_phone_number("07 98 76 54 32"))
        self.assertTrue(is_phone_number("0798765432"))
        # 08 et 09 (spéciaux et VoIP)
        self.assertTrue(is_phone_number("0800 12 34 56"))
        self.assertTrue(is_phone_number("09 70 12 34 56"))

    def test_international_formats(self):
        self.assertTrue(is_phone_number("+33 2 43 28 15 10"))
        self.assertTrue(is_phone_number("+33243281510"))
        self.assertTrue(is_phone_number("0033 1 42 89 10 12"))
        self.assertTrue(is_phone_number("0033142891012"))
        self.assertTrue(is_phone_number("+33 (0)2 43 28 15 10"))

    def test_prefixed_contact_lines(self):
        self.assertTrue(is_phone_number("Tél : 02 43 28 15 10"))
        self.assertTrue(is_phone_number("Tel: 02.43.28.15.10"))
        self.assertTrue(is_phone_number("Tél. : 01 42 89 10 12"))
        self.assertTrue(is_phone_number("Fax: 02 43 28 15 11"))
        self.assertTrue(is_phone_number("Téléphone : 01 23 45 67 89"))
        self.assertTrue(is_phone_number("Mobile : 06 12 34 56 78"))

    def test_clean_serial_number_rejects_phones(self):
        self.assertEqual(clean_serial_number("02 43 28 15 10"), "")
        self.assertEqual(clean_serial_number("0243281510"), "")
        self.assertEqual(clean_serial_number("01-42-89-10-12"), "")
        self.assertEqual(clean_serial_number("+33 2 43 28 15 10"), "")
        self.assertEqual(clean_serial_number("Tél : 02 43 28 15 10"), "")


class TestCompactDateDetection(unittest.TestCase):
    """Vérification de la détection des dates au format compact YYYYMMDD ou DDMMYYYY."""

    def test_dates_compactes(self):
        self.assertTrue(is_compact_date("20251107"))
        self.assertTrue(is_compact_date("07112025"))
        self.assertTrue(is_compact_date("20250430"))
        self.assertTrue(is_compact_date("30042025"))

    def test_vrais_numeros_non_dates(self):
        # Numéro Starkey à 8 chiffres
        self.assertFalse(is_compact_date("24108923"))
        # Numéro Signia à 8 chiffres
        self.assertFalse(is_compact_date("10340289"))
        # Numéro Widex à 6 chiffres
        self.assertFalse(is_compact_date("208950"))
        self.assertFalse(is_compact_date("934534"))


class TestLegitimateSerialPreservation(unittest.TestCase):
    """Garantie de non-régression sur tous les vrais formats de numéros de série des fabricants."""

    def test_widex_serials(self):
        self.assertFalse(is_phone_number("208950"))
        self.assertFalse(is_phone_number("934534"))
        self.assertFalse(is_phone_number("934564"))
        self.assertEqual(clean_serial_number("208950"), "208950")
        self.assertEqual(clean_serial_number("934534"), "934534")

    def test_signia_serials(self):
        self.assertFalse(is_phone_number("10340289"))
        self.assertEqual(clean_serial_number("10340289"), "10340289")

    def test_starkey_serials(self):
        self.assertFalse(is_phone_number("24108923"))
        self.assertEqual(clean_serial_number("24108923"), "24108923")

    def test_phonak_serials(self):
        self.assertFalse(is_phone_number("2622x1GMK"))
        # 10 chiffres commençant par 21 (valide car ne commence pas par 0)
        self.assertFalse(is_phone_number("2141401568"))
        self.assertEqual(clean_serial_number("2622x1GMK"), "2622X1GMK")
        self.assertEqual(clean_serial_number("2141401568"), "2141401568")

    def test_atelier_embout_serials(self):
        self.assertFalse(is_phone_number("250618GUAN1"))
        self.assertFalse(is_phone_number("250618GUAN2"))
        self.assertEqual(clean_serial_number("250618GUAN1"), "250618GUAN1")


class TestInvoiceParserSerialFiltering(unittest.TestCase):
    """Vérification sur documents complets avec en-têtes contenant téléphones, faxes et adresses."""

    def test_invoice_with_company_phone_and_fax(self):
        text = """
        SARL APPAREILLAGE AUDITIF DU MANS
        12 Rue des Alouettes 72000 LE MANS
        Tél : 02 43 28 15 10 - Fax : 02 43 28 15 11
        RCS Le Mans 123 456 789 - TVA FR 12 123456789
        Facture n° FA2025-001
        Date : 15/05/2025
        Client C38015218
        Widex MOMENT 440 mRIC
        N° de série : 934534 - 934564
        Total HT : 1500,00 EUR
        Total TTC : 1800,00 EUR
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        serials = parsed["serial_numbers"]
        # Vrais S/N extraits
        self.assertIn("934534", serials)
        self.assertIn("934564", serials)
        # Téléphones et coordonnées NON présents
        self.assertNotIn("0243281510", serials)
        self.assertNotIn("0243281511", serials)
        self.assertNotIn("02 43 28 15 10", serials)
        self.assertNotIn("72000", serials)
        self.assertNotIn("123456789", serials)
        self.assertNotIn("15052025", serials)
        self.assertNotIn("FA2025-001", serials)
        self.assertNotIn("C38015218", serials)

    def test_invoice_tabular_column_serials(self):
        text = """
        SONOVA PHONAK FRANCE SAS
        Service après-vente
        Téléphone : 01 42 89 10 12
        Contact SAV : contact@phonak.com
        Code client : C998877
        Page 1 / 1
        Date de facture : 20-04-2025
        Facture N° FAC-987654
        N° de série
        2141401568
        24108923
        Total H.T. : 800,00
        Total T.T.C. : 960,00
        """
        boxes = []
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        for i, line in enumerate(lines):
            # Simulation position spatiale : colonne N° de série avec éléments en dessous
            y_pos = 100.0 + (i * 25.0)
            x_pos = 200.0 if "2141401568" in line or "24108923" in line or "N° de série" in line else 50.0
            boxes.append({
                "text": line,
                "confidence": 0.98,
                "box": [[x_pos, y_pos], [x_pos + 120, y_pos], [x_pos + 120, y_pos + 20], [x_pos, y_pos + 20]]
            })

        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        serials = parsed["serial_numbers"]
        self.assertIn("2141401568", serials)
        self.assertIn("24108923", serials)
        self.assertNotIn("0142891012", serials)
        self.assertNotIn("01 42 89 10 12", serials)
        self.assertNotIn("C998877", serials)
        self.assertNotIn("20042025", serials)
        self.assertNotIn("FAC-987654", serials)

    def test_phonak_real_multi_delivery_invoice(self):
        """Cas réel : Facture Phonak multi-livraisons avec numéros de livraison et modèles L30-312."""
        text = """
        PHONAK life is on
        Facture 2141401568
        Date de facture 31.07.2026
        Adresse de facturation : PHONEME AUDITION COULAINES
        Livraison 2186712517 du 06.07.2026
        050-1091-P6 Phonak Audéo L30-312 1 PCS
        SN: (2623X1XVY)
        Livraison 2186712386 du 06.07.2026
        050-1091-P6 Phonak Audéo L30-312 1 PCS
        SN: (2623X1XYJ)
        Livraison 2186713992 du 07.07.2026
        Phonak Audéo I50-R 2 PCS
        SN: (2626X07MU, 2626X07MV)
        Phonak ChargerGo RIC I
        SN: (2619F10YE5)
        Total Hors taxes 1067,39
        Total T.T.C. 1129,25
        """
        boxes = []
        for i, line in enumerate(text.strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            boxes.append({
                "text": line,
                "confidence": 0.98,
                "box": [[50.0, 50.0 + i * 20.0], [300.0, 50.0 + i * 20.0], [300.0, 68.0 + i * 20.0], [50.0, 68.0 + i * 20.0]]
            })

        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        serials = parsed["serial_numbers"]
        # Vrais S/N présents
        self.assertIn("2623X1XVY", serials)
        self.assertIn("2623X1XYJ", serials)
        self.assertIn("2626X07MU", serials)
        self.assertIn("2626X07MV", serials)
        self.assertIn("2619F10YE5", serials)

        # Faux positifs EXCLUS
        self.assertNotIn("2186712386", serials)  # Numéro de livraison
        self.assertNotIn("2186712517", serials)  # Numéro de livraison
        self.assertNotIn("2186713992", serials)  # Numéro de livraison
        self.assertNotIn("L30-312", serials)     # Nom de modèle
        self.assertNotIn("I50-R", serials)       # Nom de modèle
        self.assertNotIn("2141401568", serials)  # Numéro de facture


if __name__ == "__main__":
    unittest.main()

