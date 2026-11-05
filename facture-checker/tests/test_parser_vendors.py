#!/usr/bin/env python3
"""
Tests unitaires pour les parsers multi-fournisseurs (GN Hearing, Atelier Embout, Prodition, Signia, Starkey, Widex).
"""

import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.parser import InvoiceParser, parse_date_str


class TestVendorParsers(unittest.TestCase):

    def test_parse_date_formats(self):
        # GN Hearing : 07-11-25
        self.assertEqual(parse_date_str("07-11-25"), "2025-11-07")
        # Signia / Starkey : 12.06.2025
        self.assertEqual(parse_date_str("12.06.2025"), "2025-06-12")
        # L'Atelier de l'embout : 30/06/25
        self.assertEqual(parse_date_str("30/06/25"), "2025-06-30")
        # Starkey abrégé : 30-AVR-25, 05-MAI-25
        self.assertEqual(parse_date_str("30-AVR-25"), "2025-04-30")
        self.assertEqual(parse_date_str("05-MAI-25"), "2025-05-05")

    def test_gn_hearing_invoice(self):
        text = """
        GN HEARING SAS
        ReSound Beltone INTERTON
        Bâtiment Québec 19 Rue d'Arcueil 94150 RUNGIS
        Facture 14-251101831
        Page 1
        Date de Facture 07-11-25
        Date de Commande 06-11-25
        AUDITION COULAINES 21 RUE DE LA PAIX 72190 COULAINES
        ECOUTEUR SF2C MP 3L 1 39,90 39,90 100% 5,5
        PORT 1 11,99 11,99 11,99 20
        Total H.T. 11,99
        Montant TVA 2,40
        Total T.T.C. 14,39
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "14-251101831")
        self.assertEqual(parsed["date_facture"], "2025-11-07")
        self.assertAlmostEqual(parsed["montant_ht"], 11.99, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 14.39, places=2)
        self.assertAlmostEqual(parsed["montant_tva"], 2.40, places=2)
        self.assertIn("GN Hearing", parsed["fournisseur_nom"])

    def test_latelier_de_lembout(self):
        text = """
        L'ATELIER DE L'EMBOUT
        Facture n° FA003019
        En date du 30/06/25
        Code Client C161 AUDITION COULAINES
        N° série Patient Oreille Désignation Qté P.U. H.T. TVA Remise Montant HT
        250618GUAN1 GUENOLE annick D DMSM RIC résine rosé 1 28,00 5,50% 28,00
        250618GUAN2 GUENOLE annick G DMSM RIC résine rosé 1 28,00 5,50% 28,00
        Transport Ciblex 1 9,60 20,00% 9,60
        Total HT 65,60
        Total TVA 5,5% 3,08
        Total TVA 20% 1,92
        Net à payer 70,60 Euros
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "FA003019")
        self.assertEqual(parsed["date_facture"], "2025-06-30")
        self.assertAlmostEqual(parsed["montant_ht"], 65.60, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 70.60, places=2)
        self.assertAlmostEqual(parsed["montant_tva"], 5.00, places=2)
        self.assertEqual(parsed["fournisseur_nom"], "L'Atelier de l'Embout")
        self.assertIn("250618GUAN1", parsed["serial_numbers"])
        self.assertIn("250618GUAN2", parsed["serial_numbers"])
        self.assertEqual(parsed["patient_nom"], "Guenole Annick")

    def test_prodition_invoice(self):
        text = """
        PRODITION SAS
        Bernafon PHILIPS Oticon Interacoustics
        FACTURE
        Numéro de facture SOI001213878
        Date 13/05/2025
        Page 1 / 1
        AUDITION COULAINES 21 RUE DE LA PAIX
        SPEAKER 2 L 85 MINIFIT DETECT 8 36,00 36,00 50,00 144,00 5,5
        Montant H.T. 414,00
        TVA 5,5 % 22,77
        Montant total EUR 436,77
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "SOI001213878")
        self.assertEqual(parsed["date_facture"], "2025-05-13")
        self.assertAlmostEqual(parsed["montant_ht"], 414.00, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 436.77, places=2)
        self.assertAlmostEqual(parsed["montant_tva"], 22.77, places=2)
        self.assertIn("Prodition", parsed["fournisseur_nom"])

    def test_signia_invoice(self):
        text = """
        SIGNIA SAS
        Facture
        Adresse de facturation: AUDITION COULAINES
        Numéro de client: C38015218 Facture: 301/10340289 Date: 12.06.2025
        Nom du patient : beaufils
        10 10536616 TRANSPORT 1 PCE 12,88 12,88 20,00 15,46
        Montant HT EUR 12,88
        Montant T.V.A. EUR 2,58
        Montant TTC EUR 15,46
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "301/10340289")
        self.assertEqual(parsed["date_facture"], "2025-06-12")
        self.assertAlmostEqual(parsed["montant_ht"], 12.88, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 15.46, places=2)
        self.assertEqual(parsed["fournisseur_nom"], "Signia")
        self.assertEqual(parsed["patient_nom"], "Beaufils")

    def test_widex_multipage_invoice(self):
        text = """
        WIDEX HIGH DEFINITION HEARING
        Facture
        Page No 1 de 11
        Client: C38015218 Facture: 301/10109107 Date: 31.03.2025
        Widex PRO Link
        N° de série : 208950
        AA MGY RIC312D 220 Gris A
        N° de série : 934534 - 934564
        Montant HT EUR 13,53
        20,00 % TVA EUR 2,70
        Montant TTC EUR 16,23
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "301/10109107")
        self.assertEqual(parsed["date_facture"], "2025-03-31")
        self.assertAlmostEqual(parsed["montant_ht"], 13.53, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 16.23, places=2)
        self.assertEqual(parsed["fournisseur_nom"], "Widex")
        self.assertEqual(parsed["page_current"], 1)
        self.assertEqual(parsed["page_total"], 11)
        self.assertIn("208950", parsed["serial_numbers"])
        self.assertIn("934534", parsed["serial_numbers"])
    def test_starkey_invoice(self):
        text = """
        STARKEY FRANCE S.A.S.
        Centre d'Affaires Silic - 6 rue de Rome 93290 TREMBLAY EN FRANCE
        Facture N° 2109673
        Date de facture : 30-AVR-25
        Client N° 100452 AUDITION COULAINES
        Evolv AI 2400 RIC R
        N° série : 24108923
        Montant Brut H.T. 650,00
        Remise 50,00
        Total Net H.T. 600,00
        TVA 5,5% 33,00
        Total TTC EUR 633,00
        """
        boxes = [{"text": line.strip(), "confidence": 0.98} for line in text.strip().splitlines() if line.strip()]
        parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
        parsed = parser.parse()

        self.assertEqual(parsed["numero_facture"], "2109673")
        self.assertEqual(parsed["date_facture"], "2025-04-30")
        self.assertAlmostEqual(parsed["montant_ht"], 600.0, places=2)
        self.assertAlmostEqual(parsed["montant_ttc"], 633.0, places=2)
        self.assertEqual(parsed["fournisseur_nom"], "Starkey")
        self.assertIn("24108923", parsed["serial_numbers"])


if __name__ == "__main__":
    unittest.main()

