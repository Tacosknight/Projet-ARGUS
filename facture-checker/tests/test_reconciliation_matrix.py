import unittest

from core.reconciliation import reconcile_invoices


class TestReconciliationMatrix(unittest.TestCase):
    def test_grouped_purchase_waiting_is_not_a_loss(self):
        result = reconcile_invoices([{
            "id": 1, "invoice_type": "FOURNISSEUR", "numero_facture": "F-1",
            "serial_numbers": ["AAA111", "BBB222"],
            "product_items": [
                {"serial_number": "AAA111", "product_name": "Phonak L30"},
                {"serial_number": "BBB222", "product_name": "Phonak L30"},
            ],
        }, {
            "id": 2, "invoice_type": "CLIENT", "numero_facture": "C-1", "patient_nom": "Martin",
            "serial_numbers": ["AAA111"], "product_items": [{"serial_number": "AAA111", "product_name": "Phonak L30"}],
        }])
        statuses = {item["serial_number"]: item["status"] for item in result["items"]}
        self.assertEqual(statuses["AAA111"], "RAPPROCHE")
        self.assertEqual(statuses["BBB222"], "ACHAT_EN_ATTENTE")
        self.assertEqual(result["kpi"]["pending_purchase_count"], 1)

    def test_sale_without_imported_purchase_requires_review(self):
        result = reconcile_invoices([{
            "id": 2, "invoice_type": "CLIENT", "numero_facture": "C-1",
            "serial_numbers": ["AAA111"], "product_items": [{"serial_number": "AAA111", "product_name": "Phonak L30"}],
        }])
        self.assertEqual(result["items"][0]["status"], "A_VERIFIER")
        self.assertIn("à vérifier", result["items"][0]["diagnostic"].lower())

    def test_model_fallback_is_probable_not_exact(self):
        result = reconcile_invoices([{
            "id": 1, "invoice_type": "FOURNISSEUR", "product_names": ["Phonak Audeo L30"],
        }, {
            "id": 2, "invoice_type": "CLIENT", "product_names": ["Phonak Audeo L30"],
        }])
        self.assertEqual(result["items"][0]["status"], "RAPPROCHE_PROBABLE")
        self.assertEqual(result["items"][0]["match_method"], "Marque + modèle probable")

    def test_ambiguous_candidates_are_not_paired(self):
        for serials in (("ABC1234", "ABC1235"), (None, None)):
            with self.subTest(serials=serials):
                invoices = [
                    {"id": 1, "invoice_type": "FOURNISSEUR", "product_items": [{"serial_number": "ABC1236" if serials[0] else None, "product_name": "Audeo L30", "unit_ttc": 100}]},
                    *[{"id": i + 2, "invoice_type": "CLIENT", "product_items": [{"serial_number": serial, "product_name": "Audeo L30", "unit_ttc": 200}]} for i, serial in enumerate(serials)],
                ]
                for order in (invoices, list(reversed(invoices))):
                    result = reconcile_invoices(order)
                    self.assertEqual(len(result["items"]), 3)
                    self.assertTrue(all(item["status"] == "A_VERIFIER" for item in result["items"]))
                    self.assertTrue(all(not item["prix_comparable"] for item in result["items"]))
                    self.assertEqual(result["kpi"]["rapproches_count"], 0)

    def test_duplicate_serials_on_either_side_are_reviewed(self):
        for duplicate_type in ("FOURNISSEUR", "CLIENT"):
            with self.subTest(duplicate_type=duplicate_type):
                invoices = [{"id": 1, "invoice_type": "FOURNISSEUR", "serial_numbers": ["ABC1234"]},
                            {"id": 2, "invoice_type": "CLIENT", "serial_numbers": ["abc1234"]},
                            {"id": 3, "invoice_type": duplicate_type, "serial_numbers": ["ABC1234"]}]
                result = reconcile_invoices(invoices)
                self.assertEqual(len(result["items"]), 3)
                self.assertTrue(all(item["status"] == "A_VERIFIER" for item in result["items"]))
                self.assertTrue(all("dupliqué" in item["diagnostic"] for item in result["items"]))

    def test_exact_serial_precedes_ocr_and_model_candidates(self):
        result = reconcile_invoices([
            {"id": 1, "invoice_type": "FOURNISSEUR", "product_items": [{"serial_number": "ABC1234", "product_name": "Audeo L30"}]},
            {"id": 2, "invoice_type": "CLIENT", "product_items": [{"serial_number": "ABC1235", "product_name": "Audeo L30"}]},
            {"id": 3, "invoice_type": "CLIENT", "product_items": [{"serial_number": "ABC1234", "product_name": "Audeo L30"}]},
        ])
        self.assertEqual(result["items"][0]["status"], "RAPPROCHE")
        self.assertEqual(result["items"][0]["vente_invoice_id"], 3)

    def test_multiple_purchases_competing_for_sale_are_reviewed(self):
        result = reconcile_invoices([
            {"id": 1, "invoice_type": "FOURNISSEUR", "product_names": ["Audeo L30"]},
            {"id": 2, "invoice_type": "FOURNISSEUR", "product_names": ["Audeo L30"]},
            {"id": 3, "invoice_type": "CLIENT", "product_names": ["Audeo L30"]},
        ])
        self.assertEqual([item["status"] for item in result["items"]], ["A_VERIFIER"] * 3)

    def test_linked_credit_is_reported(self):
        result = reconcile_invoices([{
            "id": 1, "invoice_type": "FOURNISSEUR", "serial_numbers": ["AAA111"],
        }, {
            "id": 2, "invoice_type": "CLIENT", "serial_numbers": ["AAA111"],
        }, {
            "id": 3, "invoice_type": "CLIENT", "document_type": "AVOIR", "related_invoice_id": 2, "numero_facture": "AV-1",
        }])
        self.assertIn("AV-1", result["items"][0]["avoirs"])


if __name__ == "__main__":
    unittest.main()
