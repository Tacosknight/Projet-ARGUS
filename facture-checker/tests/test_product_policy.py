import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.product_policy import billable_products, non_sale_reason
from core.parser import InvoiceParser, parse_invoice
from core.reconciliation import reconcile_invoices
from core.comparator import compare_invoices, compare_serial_numbers, STATUS_MATCH, STATUS_WARNING
from core.multipage import consolidate_pages
from storage.database import InvoiceDatabase


def invoice(kind="FOURNISSEUR"):
    return {
        "invoice_type": kind,
        "product_items": [
            {"product_name": "Demo Widex Moment 440", "serial_number": "DEMO123"},
            {"product_name": "Oticon Intent 1 Trial", "serial_number": "TRIAL123"},
            {"product_name": "Widex Moment 440", "serial_number": "SALE123", "unit_ttc": 0},
        ],
        "product_names": ["Demo Widex Moment 440", "Oticon Intent 1 Trial", "Widex Moment 440"],
        "serial_numbers": ["DEMO123", "TRIAL123", "SALE123"],
        "montant_ttc": 1200,
    }


class TestProductPolicy(unittest.TestCase):
    def test_whole_words_case_accents_and_punctuation(self):
        for label in ("Demo", "DEMO appareil", "appareil (trial)", "Démo-Widex", "Widex TRIAL"):
            with self.subTest(label=label):
                self.assertTrue(non_sale_reason(label))
        for label in ("Demant", "Demographie", "Triality", "Demonstration", "Widex 440", "industrial"):
            with self.subTest(label=label):
                self.assertFalse(non_sale_reason(label))

    def test_view_is_non_destructive_and_keeps_zero_priced_sale(self):
        source = invoice()
        before = copy.deepcopy(source)
        view = billable_products(source)
        self.assertEqual(view["serial_numbers"], ["SALE123"])
        self.assertEqual(view["product_names"], ["Widex Moment 440"])
        self.assertEqual(len(view["product_items"]), 1)
        self.assertEqual(view["montant_ttc"], 1200)
        self.assertEqual(source, before)

    def test_designation_and_metadata_are_checked_independently(self):
        for extra in ({"designation": "Demo"}, {"non_sale_reason": "trial"}):
            source = {"product_items": [{"product_name": "Widex Moment 440", "serial_number": "AAA123", **extra}],
                      "product_names": ["Widex Moment 440"], "serial_numbers": ["aaa123"]}
            with self.subTest(extra=extra):
                view = billable_products(source)
                self.assertFalse(view["product_items"])
                self.assertFalse(view["product_names"])
                self.assertFalse(view["serial_numbers"])

    def test_same_model_commercial_item_is_not_excluded(self):
        source = {"product_items": [
            {"product_name": "Widex Moment 440", "serial_number": "FREE123", "non_sale_reason": "demo"},
            {"product_name": "Widex Moment 440", "serial_number": "SALE123"},
        ], "product_names": ["Widex Moment 440"], "serial_numbers": ["FREE123", "SALE123"]}
        view = billable_products(source)
        self.assertEqual(view["serial_numbers"], ["SALE123"])
        self.assertEqual(view["product_names"], ["Widex Moment 440"])

    def test_fallbacks_and_json_cannot_reintroduce_excluded_items(self):
        for source in (
            {"product_names": ["Widex Trial", "Oticon Demo"]},
            {"product_items": [{"product_name": "Widex Trial", "serial_number": "FREE123"}],
             "serial_numbers": ["FREE123"], "product_names": ["Widex Trial"]},
        ):
            for serialized in (False, True):
                doc = {key: json.dumps(value) if serialized else value for key, value in source.items()}
                doc["invoice_type"] = "FOURNISSEUR"
                with self.subTest(doc=doc):
                    result = reconcile_invoices([doc])
                    self.assertEqual(result["items"], [])
                    self.assertEqual(result["kpi"]["total_items"], 0)

    def test_reconciliation_purchases_and_sales(self):
        for kind in ("FOURNISSEUR", "CLIENT"):
            result = reconcile_invoices([invoice(kind)])
            self.assertEqual([row["serial_number"] for row in result["items"]], ["SALE123"])
        result = reconcile_invoices([invoice(), invoice("CLIENT")])
        self.assertEqual(result["kpi"]["exact_count"], 1)
        self.assertEqual(result["kpi"]["pending_purchase_count"], 0)
        self.assertEqual(result["kpi"]["to_review_count"], 0)

    def test_comparator_filters_models_and_serials_without_mutation(self):
        purchase, sale = invoice(), invoice("CLIENT")
        before = copy.deepcopy([purchase, sale])
        result = compare_invoices(purchase, sale)
        products = next(row for row in result["rows"] if row["category"] == "products")
        serials = next(row for row in result["rows"] if row["category"] == "serials")
        self.assertEqual(products["vendor_val"], "Widex Moment 440")
        self.assertEqual(serials["vendor_val"], "SALE123")
        self.assertEqual(len(serials["items"]), 1)
        self.assertEqual(serials["status"], STATUS_MATCH)
        self.assertEqual([purchase, sale], before)

    def test_only_free_items_produce_neutral_comparison(self):
        purchase = invoice()
        purchase["product_items"] = purchase["product_items"][:2]
        purchase["product_names"] = purchase["product_names"][:2]
        purchase["serial_numbers"] = purchase["serial_numbers"][:2]
        status, rows, text = compare_serial_numbers(purchase["serial_numbers"], [], purchase["product_items"], [])
        self.assertEqual((status, rows), (STATUS_MATCH, []))
        self.assertIn("Demo/Trial exclus", text)
        comparison = compare_invoices(purchase, {})
        for row in comparison["rows"]:
            if row["category"] in ("products", "serials"):
                self.assertEqual(row["status"], STATUS_MATCH)
                self.assertIn("Demo/Trial exclus", row["detail"])
        self.assertEqual(compare_serial_numbers([], [])[0], STATUS_WARNING)

    def test_parser_keeps_original_names_and_serials_with_source_metadata(self):
        for label in ("Demo Widex Moment 440", "Widex Moment 440 Trial", "Démo Widex Moment 440"):
            boxes = [{"text": label}, {"text": "N° Série : 2422X1GMK"}]
            parser = InvoiceParser(boxes, forced_type="FOURNISSEUR")
            names, items = parser.extract_products(["2422X1GMK"])
            self.assertEqual(names, ["Widex Moment 440"])
            self.assertEqual(items[0]["serial_number"], "2422X1GMK")
            self.assertIn(items[0]["non_sale_reason"], ("demo", "trial"))
            self.assertEqual(billable_products({"product_names": names, "product_items": items,
                                               "serial_numbers": ["2422X1GMK"]})["serial_numbers"], [])

    def test_parser_mixed_same_model_is_classified_per_source_line(self):
        boxes = [{"text": line} for line in (
            "Demo Widex Moment 440", "N° Série : 2422X1GMK",
            "Widex Moment 440", "N° Série : 2423X1XYJ",
        )]
        parser = InvoiceParser(boxes)
        names, items = parser.extract_products(["2422X1GMK", "2423X1XYJ"])
        view = billable_products({"product_names": names, "product_items": items,
                                  "serial_numbers": ["2422X1GMK", "2423X1XYJ"]})
        self.assertEqual(view["serial_numbers"], ["2423X1XYJ"])
        self.assertEqual(len(view["product_items"]), 1)
        # Sans série aussi, conserver la ligne commerciale du même modèle.
        names, items = parser.extract_products()
        view = billable_products({"product_names": names, "product_items": items})
        self.assertEqual(len(view["product_items"]), 1)

    def test_full_parse_preserves_serial_detection_and_totals(self):
        boxes = [{"text": line, "confidence": 0.99} for line in (
            "SONOVA FRANCE SAS", "Facture N° 58837130", "Date : 03/06/2026",
            "Demo Widex Moment 440", "N° Série : 2422X1GMK",
            "Widex Moment 440", "N° Série : 2423X1XYJ",
            "Montant HT : 128.90 €", "TVA 5.5% : 7.09 €", "Total TTC : 135.99 €",
        )]
        parsed = parse_invoice(boxes, forced_type="FOURNISSEUR")
        self.assertIn("2422X1GMK", parsed["serial_numbers"])
        self.assertIn("2423X1XYJ", parsed["serial_numbers"])
        result = reconcile_invoices([parsed])
        self.assertEqual([row["serial_number"] for row in result["items"]], ["2423X1XYJ"])
        commercial = parse_invoice([{**box, "text": box["text"].replace("Demo ", "")} for box in boxes],
                                   forced_type="FOURNISSEUR")
        for key in ("serial_numbers", "montant_ht", "montant_tva", "montant_ttc", "numero_facture", "date_facture"):
            self.assertEqual(parsed[key], commercial[key])

    def test_unrelated_raw_text_never_excludes_invoice(self):
        source = invoice()
        source["product_items"] = source["product_items"][2:]
        source["product_names"] = source["product_names"][2:]
        source["serial_numbers"] = source["serial_numbers"][2:]
        source["raw_text"] = "Notre service Demo / Trial est disponible"
        self.assertEqual(reconcile_invoices([source])["kpi"]["total_items"], 1)

    def test_multipage_and_database_preserve_details_but_exclude_from_matrix(self):
        pages = []
        for page, label in enumerate(("Demo Widex Moment 440", "Oticon Intent 1 Trial"), 1):
            parsed = parse_invoice([{"text": label, "confidence": 0.99}], forced_type="FOURNISSEUR")
            parsed.update(page_current=page, page_total=2, filename=f"page{page}.png")
            pages.append(parsed)
        consolidated = consolidate_pages(pages)
        self.assertEqual(len(consolidated["product_items"]), 2)
        with tempfile.TemporaryDirectory() as directory:
            db = InvoiceDatabase(db_path=str(Path(directory) / "invoices.db"))
            db.init_db()
            consolidated.update(filename="demo.pdf", unique_hash="demo-policy-test", status="VALIDE")
            inv_id = db.save_invoice(consolidated)
            fetched = db.get_invoice_by_id(inv_id)
            self.assertEqual(fetched["product_items"], consolidated["product_items"])
            self.assertEqual(reconcile_invoices([fetched])["items"], [])


if __name__ == "__main__":
    unittest.main()
