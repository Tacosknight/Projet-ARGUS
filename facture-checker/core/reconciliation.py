"""
Module de rapprochement (réconciliation) et corrélation Factures Fournisseurs <-> Factures Clients.
Utilise les Numéros de Série uniques (S/N) des prothèses auditives pour lier
les dépenses d'achat fabricants et les refacturations aux patients.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("FactureChecker.Reconciliation")


def find_fuzzy_match(sn_target: str, pool: Any) -> Optional[str]:
    """Recherche un numéro de série exact ou tolérant au bruit OCR (préfixe >= 7 car ou 1 faute d'OCR)."""
    keys = list(pool.keys()) if hasattr(pool, "keys") else list(pool)
    if sn_target in keys:
        return sn_target
    for cand in keys:
        if (sn_target in cand or cand in sn_target) and min(len(sn_target), len(cand)) >= 7:
            return cand
        if len(sn_target) == len(cand) and sum(1 for a, b in zip(sn_target, cand) if a != b) <= 1:
            return cand
    return None


class ReconciliationEngine:

    """
    Moteur déterministe de rapprochement des factures d'achat et de vente
    par numéro de série unique (S/N).
    """

    STATUS_RAPPROCHE = "RAPPROCHE"
    STATUS_NON_REFACTURE = "NON_REFACTURE"
    STATUS_ACHAT_MANQUANT = "ACHAT_NON_TROUVE"

    def __init__(self, invoices: List[Dict[str, Any]]) -> None:
        self.invoices = invoices
        self.vendor_invoices = [
            inv for inv in invoices if (inv.get("invoice_type") or "").upper() == "FOURNISSEUR"
        ]
        self.client_invoices = [
            inv for inv in invoices if (inv.get("invoice_type") or "").upper() == "CLIENT"
        ]

    def perform_reconciliation(self) -> Dict[str, Any]:
        """
        Exécute le rapprochement par numéro de série (S/N) entre achats et ventes.

        Returns:
            Dict[str, Any]:
                - "items": Liste des appareils rapprochés avec détails financiers
                - "kpi": Métriques synthétiques (taux de couverture, volume orphelin, marge)
        """
        # Helper pour récupérer le produit associé à un S/N dans une facture
        def get_sn_product(inv: Dict[str, Any], target_sn: str) -> str:
            # Recherche dans product_items si présent
            for it in inv.get("product_items") or []:
                if str(it.get("serial_number", "")).strip().upper() == target_sn:
                    return it.get("product_name", "")
            # Recherche dans product_names
            p_names = inv.get("product_names") or []
            if isinstance(p_names, str):
                import json
                try:
                    p_names = json.loads(p_names)
                except Exception:
                    p_names = [p_names] if p_names else []
            if len(p_names) == 1:
                return p_names[0]
            elif p_names:
                return ", ".join(p_names)
            return ""

        # 1. Indexation des S/N côté Fournisseurs (Achats)
        # S/N -> Liste d'entrées d'achat
        purchases_by_sn: Dict[str, List[Dict[str, Any]]] = {}
        for inv in self.vendor_invoices:
            serials = inv.get("serial_numbers") or []
            if isinstance(serials, str):
                import json
                try:
                    serials = json.loads(serials)
                except Exception:
                    serials = []

            nb_devices = max(1, len(serials))
            # Répartition équitable du montant par appareil si facture groupée
            unit_ht = round((inv.get("montant_ht") or 0.0) / nb_devices, 2)
            unit_ttc = round((inv.get("montant_ttc") or 0.0) / nb_devices, 2)

            for sn in serials:
                norm_sn = str(sn).strip().upper()
                if not norm_sn:
                    continue
                if norm_sn not in purchases_by_sn:
                    purchases_by_sn[norm_sn] = []
                purchases_by_sn[norm_sn].append({
                    "invoice": inv,
                    "product_name": get_sn_product(inv, norm_sn),
                    "unit_ht": unit_ht,
                    "unit_ttc": unit_ttc,
                })

        # 2. Indexation des S/N côté Clients (Ventes / Refacturations)
        # S/N -> Liste d'entrées de vente
        sales_by_sn: Dict[str, List[Dict[str, Any]]] = {}
        for inv in self.client_invoices:
            serials = inv.get("serial_numbers") or []
            if isinstance(serials, str):
                import json
                try:
                    serials = json.loads(serials)
                except Exception:
                    serials = []

            nb_devices = max(1, len(serials))
            unit_ht = round((inv.get("montant_ht") or 0.0) / nb_devices, 2)
            unit_ttc = round((inv.get("montant_ttc") or 0.0) / nb_devices, 2)

            for sn in serials:
                norm_sn = str(sn).strip().upper()
                if not norm_sn:
                    continue
                if norm_sn not in sales_by_sn:
                    sales_by_sn[norm_sn] = []
                sales_by_sn[norm_sn].append({
                    "invoice": inv,
                    "product_name": get_sn_product(inv, norm_sn),
                    "unit_ht": unit_ht,
                    "unit_ttc": unit_ttc,
                })

        # 3. Réconciliation avec tolérance OCR (exacte ou quasi-exacte à 1 caractère près)
        matched_purchases: Set[str] = set()
        matched_sales: Set[str] = set()

        # Croisement des achats et ventes
        all_serials = sorted(list(set(purchases_by_sn.keys()) | set(sales_by_sn.keys())))
        reconciled_items: List[Dict[str, Any]] = []

        total_achats_reconcilies = 0.0
        total_ventes_reconciliees = 0.0
        total_achats_orphelins = 0.0  # Dépenses non refacturées

        rapproches_count = 0
        orphelins_count = 0
        achats_manquants_count = 0

        # Passe 1 : Réconciliation des achats avec les ventes
        for p_sn, p_list in purchases_by_sn.items():
            if p_sn in matched_purchases:
                continue
            matched_s_sn = find_fuzzy_match(p_sn, sales_by_sn)
            if matched_s_sn and matched_s_sn not in matched_sales:
                matched_purchases.add(p_sn)
                matched_sales.add(matched_s_sn)
                s_list = sales_by_sn[matched_s_sn]

                p_item = p_list[0]
                s_item = s_list[0]
                p_inv = p_item["invoice"]
                s_inv = s_item["invoice"]

                prix_achat_ttc = p_item["unit_ttc"]
                prix_vente_ttc = s_item["unit_ttc"]
                prix_achat_ht = p_item["unit_ht"]
                prix_vente_ht = s_item["unit_ht"]

                diff_ttc = round(prix_vente_ttc - prix_achat_ttc, 2)
                if abs(diff_ttc) <= 0.05:
                    diagnostic = "Équilibré (Refacturation exacte à 100%)"
                elif diff_ttc > 0:
                    diagnostic = f"Marge positive (+{diff_ttc:.2f} €)"
                else:
                    diagnostic = f"Attention : Vente inférieure au coût d'achat ({diff_ttc:.2f} €)"

                total_achats_reconcilies += prix_achat_ttc
                total_ventes_reconciliees += prix_vente_ttc
                rapproches_count += 1

                reconciled_items.append({
                    "serial_number": p_sn,
                    "produit_nom": p_item.get("product_name") or s_item.get("product_name") or "-",
                    "status": self.STATUS_RAPPROCHE,
                    "diagnostic": diagnostic,
                    "fournisseur_nom": p_inv.get("fournisseur_nom") or "Fabricant",
                    "achat_num_facture": p_inv.get("numero_facture"),
                    "achat_date": p_inv.get("date_facture"),
                    "achat_prix_ht": prix_achat_ht,
                    "achat_prix_ttc": prix_achat_ttc,
                    "achat_fichier": p_inv.get("filename"),
                    "patient_nom": s_inv.get("patient_nom") or "Patient",
                    "vente_num_facture": s_inv.get("numero_facture"),
                    "vente_date": s_inv.get("date_facture"),
                    "vente_prix_ht": prix_vente_ht,
                    "vente_prix_ttc": prix_vente_ttc,
                    "vente_fichier": s_inv.get("filename"),
                    "ecart_ttc": diff_ttc,
                })
            else:
                # Achats orphelins (Non refacturés)
                matched_purchases.add(p_sn)
                p_item = p_list[0]
                p_inv = p_item["invoice"]
                prix_achat_ttc = p_item["unit_ttc"]
                prix_achat_ht = p_item["unit_ht"]

                total_achats_orphelins += prix_achat_ttc
                orphelins_count += 1

                reconciled_items.append({
                    "serial_number": p_sn,
                    "produit_nom": p_item.get("product_name") or "-",
                    "status": self.STATUS_NON_REFACTURE,
                    "diagnostic": "Dépense non refacturée (aucune facture patient trouvée)",
                    "fournisseur_nom": p_inv.get("fournisseur_nom") or "Fabricant",
                    "achat_num_facture": p_inv.get("numero_facture"),
                    "achat_date": p_inv.get("date_facture"),
                    "achat_prix_ht": prix_achat_ht,
                    "achat_prix_ttc": prix_achat_ttc,
                    "achat_fichier": p_inv.get("filename"),
                    "patient_nom": "-",
                    "vente_num_facture": "-",
                    "vente_date": "-",
                    "vente_prix_ht": None,
                    "vente_prix_ttc": None,
                    "vente_fichier": None,
                    "ecart_ttc": -prix_achat_ttc,
                })

        # Passe 2 : Ventes sans achat trouvé
        for s_sn, s_list in sales_by_sn.items():
            if s_sn in matched_sales:
                continue
            matched_sales.add(s_sn)
            s_item = s_list[0]
            s_inv = s_item["invoice"]
            prix_vente_ttc = s_item["unit_ttc"]
            prix_vente_ht = s_item["unit_ht"]
            achats_manquants_count += 1

            reconciled_items.append({
                "serial_number": s_sn,
                "produit_nom": s_item.get("product_name") or "-",
                "status": self.STATUS_ACHAT_MANQUANT,
                "diagnostic": "Facture d'achat fabricant non archivée pour cet appareil",
                "fournisseur_nom": s_inv.get("fournisseur_nom") or "Non archivé",
                "achat_num_facture": "-",
                "achat_date": "-",
                "achat_prix_ht": None,
                "achat_prix_ttc": None,
                "achat_fichier": None,
                "patient_nom": s_inv.get("patient_nom") or "Non renseigné",
                "vente_num_facture": s_inv.get("numero_facture"),
                "vente_date": s_inv.get("date_facture"),
                "vente_prix_ht": prix_vente_ht,
                "vente_prix_ttc": prix_vente_ttc,
                "vente_fichier": s_inv.get("filename"),
                "ecart_ttc": prix_vente_ttc,
            })

        # Fin du traitement
        all_serials = [it["serial_number"] for it in reconciled_items]
        total_sn = len(all_serials)
        taux_couverture = round((rapproches_count / total_sn * 100.0) if total_sn > 0 else 0.0, 1)

        kpi_summary = {
            "total_serials_detected": total_sn,
            "rapproches_count": rapproches_count,
            "non_refactures_count": orphelins_count,
            "achats_manquants_count": achats_manquants_count,
            "taux_couverture": taux_couverture,
            "volume_achats_reconcilies": round(total_achats_reconcilies, 2),
            "volume_ventes_reconciliees": round(total_ventes_reconciliees, 2),
            "volume_dépenses_orphelines": round(total_achats_orphelins, 2),
            "solde_net_reconcilie": round(total_ventes_reconciliees - total_achats_reconcilies, 2),
        }

        return {
            "items": reconciled_items,
            "kpi": kpi_summary,
        }


def reconcile_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Point d'entrée utilitaire pour le rapprochement Fournisseur / Client."""
    engine = ReconciliationEngine(invoices)
    return engine.perform_reconciliation()
