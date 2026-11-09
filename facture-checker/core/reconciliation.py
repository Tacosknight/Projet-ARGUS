"""Matrice de rapprochement documentaire Achats ↔ Clients.

Une facture fournisseur peut être groupée : l'absence d'une vente dans les
documents importés est donc un état d'attente, jamais une perte présumée.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from thefuzz import fuzz

logger = logging.getLogger("FactureChecker.Reconciliation")

STATUS_EXACT = "RAPPROCHE"
STATUS_PROBABLE = "RAPPROCHE_PROBABLE"
STATUS_PENDING = "ACHAT_EN_ATTENTE"
STATUS_REVIEW = "A_VERIFIER"
STATUS_CREDIT = "AVOIR_RATTACHE"


def find_fuzzy_match(sn_target: str, pool: Any) -> Optional[str]:
    """Recherche exacte ou tolérante à une seule erreur OCR sur un S/N."""
    keys = list(pool.keys()) if hasattr(pool, "keys") else list(pool)
    if sn_target in keys:
        return sn_target
    for candidate in keys:
        if (sn_target in candidate or candidate in sn_target) and min(len(sn_target), len(candidate)) >= 7:
            return candidate
        if len(sn_target) == len(candidate) and sum(a != b for a, b in zip(sn_target, candidate)) <= 1:
            return candidate
    return None


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except Exception:
            return [value] if value else []
    return []


def _product_match(left: str, right: str) -> bool:
    left_norm, right_norm = _normalize_product(left or ""), _normalize_product(right or "")
    return bool(left_norm and right_norm and (
        left_norm == right_norm or left_norm in right_norm or right_norm in left_norm or fuzz.ratio(left_norm, right_norm) >= 75
    ))


def _normalize_product(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8").lower()
    for brand in ("phonak", "widex", "signia", "oticon", "starkey", "resound", "bernafon", "philips", "sonova", "unitron", "demant"):
        value = re.sub(rf"^{brand}\s+", "", value)
    return re.sub(r"[ \t\-_./&*,+]+", "", value)


def _entries(invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise les lignes disponibles sans inventer de prix unitaire."""
    items = _as_list(invoice.get("product_items"))
    serials = [str(value).strip().upper() for value in _as_list(invoice.get("serial_numbers")) if str(value).strip()]
    result: List[Dict[str, Any]] = []
    used_serials = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        serial = str(item.get("serial_number") or "").strip().upper() or None
        if serial:
            used_serials.add(serial)
        name = item.get("product_name") or item.get("designation") or ""
        result.append({
            "invoice": invoice,
            "serial_number": serial,
            "product_name": str(name).strip(),
            "quantity": float(item.get("quantity") or 1),
            "unit_ht": item.get("unit_ht"),
            "unit_ttc": item.get("unit_ttc"),
            "source": "ligne OCR" if name else "S/N OCR",
        })
    for serial in serials:
        if serial not in used_serials:
            result.append({"invoice": invoice, "serial_number": serial, "product_name": "", "quantity": 1.0, "unit_ht": None, "unit_ttc": None, "source": "S/N OCR"})
    if not result:
        for name in _as_list(invoice.get("product_names")):
            if name:
                result.append({"invoice": invoice, "serial_number": None, "product_name": str(name), "quantity": 1.0, "unit_ht": None, "unit_ttc": None, "source": "modèle OCR"})
    return result


def _invoice_data(invoice: Optional[Dict[str, Any]], prefix: str) -> Dict[str, Any]:
    if not invoice:
        return {f"{prefix}_{field}": None for field in ("invoice_id", "num_facture", "date", "fichier", "tiers")}
    return {
        f"{prefix}_invoice_id": invoice.get("id"),
        f"{prefix}_num_facture": invoice.get("numero_facture"),
        f"{prefix}_date": invoice.get("date_facture"),
        f"{prefix}_fichier": invoice.get("filename"),
        f"{prefix}_tiers": invoice.get("fournisseur_nom") if prefix == "achat" else invoice.get("patient_nom"),
    }


class ReconciliationEngine:
    def __init__(self, invoices: List[Dict[str, Any]]) -> None:
        self.invoices = invoices
        self.purchases = [invoice for invoice in invoices if (invoice.get("invoice_type") or "").upper() == "FOURNISSEUR" and (invoice.get("document_type") or "FACTURE").upper() != "AVOIR"]
        self.sales = [invoice for invoice in invoices if (invoice.get("invoice_type") or "").upper() == "CLIENT" and (invoice.get("document_type") or "FACTURE").upper() != "AVOIR"]
        self.credits = [invoice for invoice in invoices if (invoice.get("document_type") or "FACTURE").upper() == "AVOIR"]

    def _credits_for(self, invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [credit for credit in self.credits if credit.get("related_invoice_id") == invoice.get("id")]

    def _make_item(self, status: str, diagnostic: str, purchase: Optional[Dict[str, Any]], sale: Optional[Dict[str, Any]], method: str, credits: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        purchase_invoice = purchase.get("invoice") if purchase else None
        sale_invoice = sale.get("invoice") if sale else None
        price_comparable = bool(purchase and sale and purchase.get("unit_ttc") is not None and sale.get("unit_ttc") is not None)
        purchase_price = purchase.get("unit_ttc") if purchase else None
        sale_price = sale.get("unit_ttc") if sale else None
        difference = round(float(sale_price) - float(purchase_price), 2) if price_comparable else None
        credit_numbers = [credit.get("numero_facture") or f"Avoir #{credit.get('id')}" for credit in credits or []]
        if credit_numbers:
            diagnostic += f" · Avoir rattaché : {', '.join(credit_numbers)}"
        result = {
            "status": status,
            "match_method": method,
            "diagnostic": diagnostic,
            "serial_number": (purchase or sale or {}).get("serial_number") or "—",
            "produit_achat": purchase.get("product_name", "") if purchase else "",
            "produit_vente": sale.get("product_name", "") if sale else "",
            "produit_nom": (purchase or sale or {}).get("product_name") or "Non identifié",
            "quantite_achat": purchase.get("quantity") if purchase else None,
            "quantite_vente": sale.get("quantity") if sale else None,
            "achat_prix_ht": purchase.get("unit_ht") if purchase else None,
            "achat_prix_ttc": purchase_price,
            "vente_prix_ht": sale.get("unit_ht") if sale else None,
            "vente_prix_ttc": sale_price,
            "prix_comparable": price_comparable,
            "ecart_ttc": difference,
            "avoirs": credit_numbers,
            "quantity_match": bool(purchase and sale and purchase.get("quantity") == sale.get("quantity")),
        }
        result.update(_invoice_data(purchase_invoice, "achat"))
        result.update(_invoice_data(sale_invoice, "vente"))
        # Compatibilité des consommateurs existants.
        result["fournisseur_nom"] = result.get("achat_tiers") or "—"
        result["patient_nom"] = result.get("vente_tiers") or "—"
        result["achat_num_facture"] = result.get("achat_num_facture") or "—"
        result["vente_num_facture"] = result.get("vente_num_facture") or "—"
        result["achat_date"] = result.get("achat_date") or "—"
        result["vente_date"] = result.get("vente_date") or "—"
        result["achat_fichier"] = result.get("achat_fichier")
        result["vente_fichier"] = result.get("vente_fichier")
        return result

    def perform_reconciliation(self) -> Dict[str, Any]:
        purchases = [entry for invoice in self.purchases for entry in _entries(invoice)]
        sales = [entry for invoice in self.sales for entry in _entries(invoice)]
        matched_sales: set[int] = set()
        output: List[Dict[str, Any]] = []

        for purchase in purchases:
            found_index: Optional[int] = None
            method = ""
            if purchase.get("serial_number"):
                for index, sale in enumerate(sales):
                    if index in matched_sales or not sale.get("serial_number"):
                        continue
                    candidate = find_fuzzy_match(purchase["serial_number"], [sale["serial_number"]])
                    if candidate:
                        found_index, method = index, "S/N exact" if candidate == purchase["serial_number"] else "S/N tolérance OCR"
                        break
            if found_index is None and purchase.get("product_name"):
                for index, sale in enumerate(sales):
                    if index not in matched_sales and sale.get("product_name") and _product_match(purchase["product_name"], sale["product_name"]):
                        found_index, method = index, "Marque + modèle probable"
                        break
            if found_index is None:
                output.append(self._make_item(STATUS_PENDING, "Achat détecté ; aucune vente correspondante parmi les documents actuellement importés.", purchase, None, "En attente", self._credits_for(purchase["invoice"])))
                continue
            sale = sales[found_index]
            matched_sales.add(found_index)
            exact = method == "S/N exact"
            status = STATUS_EXACT if exact else STATUS_PROBABLE
            detail = "Même numéro de série détecté." if exact else f"Correspondance {method.lower()} ; confirmation humaine recommandée."
            if purchase.get("quantity") != sale.get("quantity"):
                status, detail = STATUS_REVIEW, detail + " Quantité différente."
            output.append(self._make_item(status, detail, purchase, sale, method, self._credits_for(sale["invoice"])))

        for index, sale in enumerate(sales):
            if index not in matched_sales:
                output.append(self._make_item(STATUS_REVIEW, "Vente détectée sans achat correspondant parmi les documents importés : à vérifier.", None, sale, "Achat à rechercher", self._credits_for(sale["invoice"])))

        counts = {status: sum(item["status"] == status for item in output) for status in (STATUS_EXACT, STATUS_PROBABLE, STATUS_PENDING, STATUS_REVIEW)}
        comparable = [item for item in output if item["prix_comparable"]]
        return {
            "items": output,
            "kpi": {
                "total_items": len(output), "total_serials_detected": len(output),
                "rapproches_count": counts[STATUS_EXACT] + counts[STATUS_PROBABLE],
                "exact_count": counts[STATUS_EXACT], "probable_count": counts[STATUS_PROBABLE],
                "pending_purchase_count": counts[STATUS_PENDING], "to_review_count": counts[STATUS_REVIEW],
                "non_refactures_count": counts[STATUS_PENDING], "achats_manquants_count": counts[STATUS_REVIEW],
                "taux_couverture": round((counts[STATUS_EXACT] + counts[STATUS_PROBABLE]) / len(output) * 100, 1) if output else 0.0,
                "prix_unitaires_comparables": len(comparable),
                "volume_achats_reconcilies": 0.0, "volume_ventes_reconciliees": 0.0,
                "volume_dépenses_orphelines": 0.0, "solde_net_reconcilie": 0.0,
            },
        }


def reconcile_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    return ReconciliationEngine(invoices).perform_reconciliation()
