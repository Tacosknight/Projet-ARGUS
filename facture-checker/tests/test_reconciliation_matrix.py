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
