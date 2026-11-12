"""Matrice de rapprochement documentaire Achats ↔ Clients.

Une facture fournisseur peut être groupée : l'absence d'une vente dans les
documents importés est donc un état d'attente, jamais une perte présumée.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from thefuzz import fuzz
from core.product_policy import billable_products

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
    invoice = billable_products(invoice)
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

        def duplicates(entries: List[Dict[str, Any]]) -> set[str]:
            seen: set[str] = set()
            repeated: set[str] = set()
            for entry in entries:
                serial = entry.get("serial_number")
                if serial:
                    if serial in seen:
                        repeated.add(serial)
                    seen.add(serial)
            return repeated

        repeated = duplicates(purchases) | duplicates(sales)
        review_purchases = {i for i, entry in enumerate(purchases) if entry.get("serial_number") in repeated}
        review_sales = {i for i, entry in enumerate(sales) if entry.get("serial_number") in repeated}
        matches: Dict[int, Tuple[int, str]] = {}

        # Les correspondances exactes priment sur l'OCR, puis sur le modèle.
        # Chaque lien doit être unique des deux côtés et ne pas impliquer un
        # numéro dupliqué ou une ligne déjà ambiguë.
        for method in ("S/N exact", "S/N tolérance OCR", "Marque + modèle probable"):
            candidates: Dict[int, List[int]] = {}
            for pi, purchase in enumerate(purchases):
                if pi in matches:
                    continue
                for si, sale in enumerate(sales):
                    if si in matched_sales:
                        continue
                    left, right = purchase.get("serial_number"), sale.get("serial_number")
                    if method == "S/N exact":
                        eligible = bool(left and right and left == right)
                    elif method == "S/N tolérance OCR":
                        eligible = bool(left and right and left != right and find_fuzzy_match(left, [right]))
                    else:
                        eligible = bool(purchase.get("product_name") and sale.get("product_name") and _product_match(purchase["product_name"], sale["product_name"]))
                    if eligible:
                        candidates.setdefault(pi, []).append(si)
            sale_counts: Dict[int, int] = {}
            for indices in candidates.values():
                for si in indices:
                    sale_counts[si] = sale_counts.get(si, 0) + 1
            ambiguous_purchases = {
                pi for pi, indices in candidates.items()
                if pi in review_purchases or len(indices) != 1
                or any(si in review_sales or sale_counts[si] != 1 for si in indices)
            }
            ambiguous_sales = {si for pi in ambiguous_purchases for si in candidates[pi]}
            # Un candidat relié à une ligne ambiguë ne peut pas être attribué.
            while True:
                more = {pi for pi, indices in candidates.items() if any(si in ambiguous_sales for si in indices)} - ambiguous_purchases
                if not more:
                    break
                ambiguous_purchases.update(more)
                ambiguous_sales.update(si for pi in more for si in candidates[pi])
            review_purchases.update(ambiguous_purchases)
            review_sales.update(ambiguous_sales)
            for pi, indices in candidates.items():
                if pi not in review_purchases:
                    matches[pi] = (indices[0], method)
                    matched_sales.add(indices[0])

        for index, purchase in enumerate(purchases):
            if index in review_purchases:
                output.append(self._make_item(STATUS_REVIEW, "Numéro de série dupliqué ou correspondance ambiguë : à vérifier.", purchase, None, "À vérifier", self._credits_for(purchase["invoice"])))
                continue
            if index not in matches:
                output.append(self._make_item(STATUS_PENDING, "Achat détecté ; aucune vente correspondante parmi les documents actuellement importés.", purchase, None, "En attente", self._credits_for(purchase["invoice"])))
                continue
            found_index, method = matches[index]
            sale = sales[found_index]
            exact = method == "S/N exact"
            status = STATUS_EXACT if exact else STATUS_PROBABLE
            detail = "Même numéro de série détecté." if exact else f"Correspondance {method.lower()} ; confirmation humaine recommandée."
            if purchase.get("quantity") != sale.get("quantity"):
                status, detail = STATUS_REVIEW, detail + " Quantité différente."
            output.append(self._make_item(status, detail, purchase, sale, method, self._credits_for(sale["invoice"])))

        for index, sale in enumerate(sales):
            if index not in matched_sales:
                diagnostic = ("Numéro de série dupliqué ou correspondance ambiguë : à vérifier."
                              if index in review_sales else
                              "Vente détectée sans achat correspondant parmi les documents importés : à vérifier.")
                output.append(self._make_item(STATUS_REVIEW, diagnostic, None, sale, "Achat à rechercher", self._credits_for(sale["invoice"])))

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


def grouped_client_totals(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Somme documentaire du dossier, sans allocation par appareil ni avoir."""
    total = Decimal("0")
    details = []
    seen = set()
    for invoice in invoices:
        if (invoice.get("invoice_type") or "").upper() != "CLIENT" or (invoice.get("document_type") or "FACTURE").upper() == "AVOIR":
            continue
        identity = invoice.get("id")
        if identity is not None:
            if identity in seen:
                continue
            seen.add(identity)
        try:
            amount = Decimal(str(invoice.get("montant_ttc")))
            if not amount.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            amount = None
        if amount is not None:
            total += amount
        details.append({"invoice_id": identity, "numero_facture": invoice.get("numero_facture"),
                        "filename": invoice.get("filename"), "montant_ttc": float(amount) if amount is not None else None})
    missing = sum(item["montant_ttc"] is None for item in details)
    return {"factures": details, "nombre_factures": len(details), "montants_manquants": missing,
            "total_connu_ttc": float(total), "complet": bool(details) and missing == 0}


def reconcile_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    return ReconciliationEngine(invoices).perform_reconciliation()
