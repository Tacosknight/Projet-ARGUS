"""Régressions anonymisées des mises en page WSA et Phonème fournies."""
import unittest

from core.parser import InvoiceParser
from core.multipage import consolidate_pages


def parse(text, kind):
    return InvoiceParser([{"text": line.strip(), "confidence": .99}
                          for line in text.splitlines() if line.strip()], forced_type=kind).parse()


class ClientInvoiceRegressions(unittest.TestCase):
    def test_vendor_two_pages(self):
        first = parse("""
        WS Audiology France Signia
        Facture: 301/10447160 Date: 30.09.2026
        20 10967904 1 PCE 169,00 5,50 178,30
        S_ITE SILK 3X L MOC TBLU
        Nom du patient : EXEMPLE
        Numéro de série : HKC7722
        Date fin de garantie : 17.12.2030
        21 10539532 1 PCE 0,13 5,50 0,14
        Eco-contribution
        30 10967905 1 PCE 169,00 5,50 178,30
        S_ITE SILK 3X R MOC TRD
        Nom du patient : EXEMPLE
        Numéro de série : HKC9696
        """, "FOURNISSEUR")
        second = parse("""
        WS Audiology France Signia
        Facture: 301/10447160 Date: 30.09.2026
        20 10824823 2 PCE 16,00 32,00 5,50 33,76
        MINIREC. 2.0 1R M CXX
        Numéro de série : 066193HN 076504HN
        Date fin de garantie : 24.12.2028
        30 10824822 1 PCE 16,00 16,00 5,50 16,88
        MINIREC. 2.0 1L M CXX
        Numéro de série : 069077HN
        Montant Total 412,02 26,39 438,41
        Facture à payer avant le : 14.11.2026 438,41 EUR
        """, "FOURNISSEUR")
        first['page_current'], second['page_current'] = 1, 2
        invoice = consolidate_pages([first, second])
        self.assertEqual(invoice['date_facture'], '2026-09-30')
        self.assertEqual(invoice['patient_nom'], 'Exemple')
        self.assertEqual(invoice['serial_numbers'], sorted(['HKC7722', 'HKC9696', '066193HN', '076504HN', '069077HN']))
        self.assertEqual((invoice['montant_ht'], invoice['montant_tva'], invoice['montant_ttc']), (412.02, 26.39, 438.41))
        self.assertEqual(len(invoice['product_names']), 4)
        items = {item['serial_number']: item['product_name'] for item in invoice['product_items']}
        self.assertIn('SILK 3X L', items['HKC7722'])
        self.assertIn('MINIREC. 2.0 1R', items['076504HN'])
        self.assertEqual(next(item['reference'] for item in invoice['product_items'] if item['serial_number'] == 'HKC7722'), '10967904')

    def test_patient_date_and_unlabelled_serials(self):
        invoice = parse("""
        Phonème Audition
        Facture N° 222
        Fait le : 04/11/2026
        Patient
        EXEMPLE Camille
        Date de naissance : 12/11/1975
        Date de la prescription : 22/09/2026
        SILK 3X R*
        HKC9696 Garantie 4 ans Signia
        LPP : 7379971 Deep Brown
        SILK 3X L*
        HKC7722 Garantie 4 ans Signia
        LPP : 7336186 Deep Brown
        Total 1 516,58 1 600,00 - 83,42
        Sivantos, 175 Boulevard Anatole France, 93200 Saint-Denis, SILK 3X R
        """, 'CLIENT')
        self.assertEqual(invoice['date_facture'], '2026-11-04')
        self.assertEqual(invoice['serial_numbers'], ['HKC7722', 'HKC9696'])
        self.assertIn('SILK 3X R', invoice['product_names'])
        self.assertEqual(invoice['montant_ttc'], 1600)

    def test_personal_date_never_used_as_invoice_date(self):
        invoice = parse('Date de naissance : 12/11/1975\nDate de prescription : 22/09/2026', 'CLIENT')
        self.assertIsNone(invoice['date_facture'])


if __name__ == '__main__':
    unittest.main()
