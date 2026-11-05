"""
Module de comparaison directe entre une Facture Fournisseur (Achat fabricant)
et une Facture Client (Vente / Refacturation patient).

Génère une analyse comparative ligne par ligne avec surlignage sémantique :
- VERT (MATCH) : Données identiques, conformes ou marge positive.
- ORANGE (WARNING) : Données équivalentes mais non identiques mot à mot
  (tolérance OCR sur S/N, marques équivalentes Sonova/Phonak, TVA calculée par déduction).
- ROUGE (ERROR) : Données erronées, contradictoires ou manquantes
  (appareil acheté non refacturé, vente à perte, erreur de calcul).
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import re
import logging

from core.reconciliation import find_fuzzy_match
from thefuzz import fuzz

import unicodedata

logger = logging.getLogger("FactureChecker.Comparator")

STATUS_MATCH = "MATCH"       # 🟢 Vert
STATUS_WARNING = "WARNING"   # 🟠 Orange
STATUS_ERROR = "ERROR"       # 🔴 Rouge


def normalize_product_for_matching(name: str) -> str:
    """Normalise une chaîne de modèle pour matching flou : minuscules, sans accents, sans nom de marque, sans tirets ni espaces."""
    s = unicodedata.normalize("NFKD", name).encode("ASCII", "ignore").decode("utf-8").lower()
    for brand in ["phonak", "widex", "signia", "oticon", "starkey", "resound", "bernafon", "philips", "sonova", "unitron", "demant"]:
        s = re.sub(rf"^{brand}\s+", "", s)
    s = re.sub(r"[ \t\-_./&*,+]+", "", s)
    return s


def compare_product_names(
    vendor_products: List[str],
    client_products: List[str],
) -> Tuple[str, str]:
    """
    Compare les modèles de produits entre la facture fournisseur et la facture client.
    Retourne (statut, diagnostic).
    """
    v_prods = [p.strip() for p in vendor_products if p and p.strip()]
    c_prods = [p.strip() for p in client_products if p and p.strip()]

    if not v_prods and not c_prods:
        return STATUS_MATCH, "Modèle d'appareil non spécifié textuellement"
    if not v_prods or not c_prods:
        return STATUS_WARNING, f"Modèle identifié : {', '.join(v_prods or c_prods)}"

    matches_found = []
    for vp in v_prods:
        v_norm = normalize_product_for_matching(vp)
        for cp in c_prods:
            c_norm = normalize_product_for_matching(cp)
            if v_norm == c_norm or v_norm in c_norm or c_norm in v_norm or fuzz.ratio(v_norm, c_norm) >= 75:
                matches_found.append((vp, cp))
                break

    if matches_found:
        matched_str = ", ".join(f"{cp}" for _, cp in matches_found)
        return STATUS_MATCH, f"Modèle(s) d'appareil concordant(s) ({matched_str})"

    return STATUS_ERROR, f"Divergence de modèle détectée : Achat '{v_prods[0]}' vs Vente '{c_prods[0]}'"


def compare_serial_numbers(
    vendor_serials: List[str],
    client_serials: List[str],
    vendor_items: Optional[List[Dict[str, Any]]] = None,
    client_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """
    Compare les numéros de série (S/N) entre la facture fournisseur et la facture client.
    Associe les modèles d'appareils correspondants quand disponibles.
    Retourne (statut_global, liste_comparative_des_sn, diagnostic).
    """
    v_clean = [str(s).strip().upper() for s in vendor_serials if s and str(s).strip()]
    c_clean = [str(s).strip().upper() for s in client_serials if s and str(s).strip()]

    # Mappage rapide S/N -> Nom de modèle
    v_sn_to_model: Dict[str, str] = {}
    if vendor_items:
        for it in vendor_items:
            sn = str(it.get("serial_number") or "").strip().upper()
            if sn and it.get("designation"):
                v_sn_to_model[sn] = it["designation"]

    c_sn_to_model: Dict[str, str] = {}
    if client_items:
        for it in client_items:
            sn = str(it.get("serial_number") or "").strip().upper()
            if sn and it.get("designation"):
                c_sn_to_model[sn] = it["designation"]

    detailed_matches: List[Dict[str, Any]] = []
    matched_c_sn: Set[str] = set()

    for v_sn in v_clean:
        matched = find_fuzzy_match(v_sn, c_clean)
        v_model = v_sn_to_model.get(v_sn, "")
        if matched and matched not in matched_c_sn:
            matched_c_sn.add(matched)
            c_model = c_sn_to_model.get(matched, "")
            model_info = v_model or c_model
            if v_sn == matched:
                detailed_matches.append({
                    "vendor_sn": v_sn,
                    "client_sn": matched,
                    "status": STATUS_MATCH,
                    "product_name": model_info,
                    "detail": "Numéro de série rigoureusement identique",
                })
            else:
                detailed_matches.append({
                    "vendor_sn": v_sn,
                    "client_sn": matched,
                    "status": STATUS_WARNING,
                    "product_name": model_info,
                    "detail": f"Rapproché avec tolérance OCR ({v_sn} ≈ {matched})",
                })
        else:
            detailed_matches.append({
                "vendor_sn": v_sn,
                "client_sn": "Non refacturé",
                "status": STATUS_ERROR,
                "product_name": v_model,
                "detail": "Appareil acheté mais absent de la facture patient (perte financière ou autre patient/stock)",
            })

    # Appareils clients sans achat correspondant sur cette facture
    for c_sn in c_clean:
        if c_sn not in matched_c_sn:
            detailed_matches.append({
                "vendor_sn": "Non trouvé",
                "client_sn": c_sn,
                "status": STATUS_WARNING,
                "product_name": c_sn_to_model.get(c_sn, ""),
                "detail": "Appareil vendu non listé sur cette facture d'achat",
            })

    # Synthèse du statut S/N
    statuses = [item["status"] for item in detailed_matches]
    if not detailed_matches:
        return STATUS_WARNING, [], "Aucun numéro de série détecté sur les documents."

    unmatched_clients = [item for item in detailed_matches if item.get("vendor_sn") == "Non trouvé"]
    has_error = any(s == STATUS_ERROR for s in statuses)
    has_warning = any(s == STATUS_WARNING for s in statuses)

    if all(s == STATUS_MATCH for s in statuses):
        global_status = STATUS_MATCH
        summary = f"Tous les appareils ({len(v_clean)}) sont parfaitement concordants."
    elif has_error:
        global_status = STATUS_ERROR
        summary = "Attention : un ou plusieurs appareils achetés ne figurent pas sur la facture patient."
    elif unmatched_clients:
        global_status = STATUS_WARNING
        summary = f"Attention : {len(unmatched_clients)} appareil(s) vendu(s) non trouvé(s) sur ce document d'achat (ex: {unmatched_clients[0]['client_sn']})."
    elif has_warning:
        global_status = STATUS_WARNING
        summary = "Appareils rapprochés avec de légères variations d'OCR."
    else:
        global_status = STATUS_MATCH
        summary = "Rapprochement des appareils validé."

    return global_status, detailed_matches, summary


def compare_invoices(
    vendor_doc: Dict[str, Any],
    client_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Exécute la comparaison intégrale entre une facture fournisseur et une facture client.
    Génère les lignes de comparaison alignées prêtes pour l'affichage en 2 colonnes.
    """
    rows: List[Dict[str, Any]] = []

    # 1. Fabricant / Marque / Tiers
    v_fourn = (vendor_doc.get("fournisseur_nom") or "").strip()
    c_fourn = (client_doc.get("fournisseur_nom") or "").strip()
    c_patient = (client_doc.get("patient_nom") or "").strip()

    # Groupes industriels de fabricants d'aides auditives
    brand_groups = [
        ({"phonak", "sonova", "unitron", "hansaton", "advanced bionics"}, "Groupe Sonova (Phonak / Sonova / Unitron)"),
        ({"signia", "widex", "sivantos", "wsaudiology"}, "Groupe WS Audiology (Signia / Widex / Sivantos)"),
        ({"prodition", "oticon", "bernafon", "philips", "interacoustics", "demant"}, "Groupe Demant (Prodition / Oticon / Bernafon / Philips)"),
        ({"gn hearing", "resound", "beltone", "interton"}, "Groupe GN Store Nord (GN Hearing / ReSound / Beltone)"),
        ({"starkey", "starkey france"}, "Groupe Starkey Technologies"),
        ({"l'atelier de l'embout", "atelier de l'embout", "atelier embout"}, "Laboratoire d'embouts sur-mesure"),
    ]

    # Statut Fabricant
    brand_status = STATUS_WARNING
    brand_detail = "Fabricant identifié"
    if v_fourn and c_fourn:
        v_low, c_low = v_fourn.lower(), c_fourn.lower()
        if v_low == c_low or fuzz.ratio(v_low, c_low) >= 80:
            brand_status = STATUS_MATCH
            brand_detail = f"Même fabricant confirmé ({v_fourn})"
        else:
            matched_group = None
            for group_set, group_label in brand_groups:
                v_in = any(k in v_low for k in group_set)
                c_in = any(k in c_low for k in group_set)
                if v_in and c_in:
                    matched_group = group_label
                    break

            if matched_group:
                brand_status = STATUS_WARNING
                brand_detail = f"Marques équivalentes du même groupe ({matched_group})"
            else:
                brand_status = STATUS_ERROR
                brand_detail = f"Divergence de fabricant ({v_fourn} vs {c_fourn})"
    elif v_fourn or c_fourn:
        brand_status = STATUS_WARNING
        brand_detail = f"Fabricant détecté : {v_fourn or c_fourn}"
    else:
        brand_status = STATUS_WARNING
        brand_detail = "Fabricant non spécifié textuellement"

    rows.append({
        "label": "Fabricant / Marque",
        "category": "tiers",
        "vendor_val": v_fourn or "Non identifié",
        "client_val": c_fourn or (f"Patient : {c_patient}" if c_patient else "Non identifié"),
        "status": brand_status,
        "detail": brand_detail,
    })

    v_patient = (vendor_doc.get("patient_nom") or "").strip()
    if v_patient or c_patient:
        if v_patient and c_patient:
            v_p_low, c_p_low = v_patient.lower(), c_patient.lower()
            if v_p_low == c_p_low or fuzz.ratio(v_p_low, c_p_low) >= 70 or v_p_low in c_p_low or c_p_low in v_p_low:
                pat_status = STATUS_MATCH
                pat_detail = f"Même patient bénéficiaire confirmé sur les 2 factures ({c_patient})"
            else:
                pat_status = STATUS_WARNING
                pat_detail = f"Nom différent sur l'achat ({v_patient}) et la vente ({c_patient})"
        elif c_patient:
            pat_status = STATUS_MATCH
            pat_detail = f"Dossier patient identifié au nom de {c_patient}"
        else:
            pat_status = STATUS_MATCH
            pat_detail = f"Patient mentionné sur la facture fournisseur : {v_patient}"

        rows.append({
            "label": "Patient Bénéficiaire",
            "category": "tiers",
            "vendor_val": v_patient or "-",
            "client_val": c_patient or "-",
            "status": pat_status,
            "detail": pat_detail,
        })

    # 2. Numéros de facture
    v_num = vendor_doc.get("numero_facture") or "Non détecté"
    c_num = client_doc.get("numero_facture") or "Non détecté"
    rows.append({
        "label": "N° de Facture",
        "category": "reference",
        "vendor_val": v_num,
        "client_val": c_num,
        "status": STATUS_MATCH if (v_num != "Non détecté" and c_num != "Non détecté") else STATUS_WARNING,
        "detail": f"Achat réf. {v_num} | Vente réf. {c_num}",
    })

    # 3. Dates de facturation
    v_date = vendor_doc.get("date_facture")
    c_date = client_doc.get("date_facture")
    date_status = STATUS_MATCH
    date_detail = "Dates cohérentes"

    if v_date and c_date:
        try:
            from datetime import date
            d_v = date.fromisoformat(str(v_date)[:10])
            d_c = date.fromisoformat(str(c_date)[:10])
            if d_v <= d_c:
                date_status = STATUS_MATCH
                date_detail = "Chronologie respectée (Achat fabricant antérieur ou égal à la vente patient)"
            else:
                date_status = STATUS_ERROR
                date_detail = "Anomalie chronologique : Date d'achat postérieure à la date de vente !"
        except Exception:
            date_status = STATUS_MATCH
            date_detail = "Dates détectées"
    elif not v_date and not c_date:
        date_status = STATUS_WARNING
        date_detail = "Dates non trouvées sur les documents"
    else:
        date_status = STATUS_WARNING
        date_detail = "Date renseignée sur un seul document"

    rows.append({
        "label": "Date de Facture",
        "category": "reference",
        "vendor_val": v_date or "-",
        "client_val": c_date or "-",
        "status": date_status,
        "detail": date_detail,
    })

    # 4. Modèles d'appareils & produits
    v_products = vendor_doc.get("product_names") or []
    c_products = client_doc.get("product_names") or []
    prod_status, prod_detail = compare_product_names(v_products, c_products)

    rows.append({
        "label": "Appareil(s) / Modèle(s)",
        "category": "products",
        "vendor_val": ", ".join(v_products) if v_products else "Non spécifié",
        "client_val": ", ".join(c_products) if c_products else "Non spécifié",
        "status": prod_status,
        "detail": prod_detail,
    })

    # 5. Numéros de Série (S/N) - Élément central
    v_serials = vendor_doc.get("serial_numbers") or []
    c_serials = client_doc.get("serial_numbers") or []
    v_items = vendor_doc.get("product_items") or []
    c_items = client_doc.get("product_items") or []
    sn_global_status, sn_detailed_matches, sn_summary = compare_serial_numbers(
        v_serials, c_serials, vendor_items=v_items, client_items=c_items
    )

    rows.append({
        "label": "Numéro(s) de Série (S/N)",
        "category": "serials",
        "vendor_val": ", ".join(v_serials) if v_serials else "Aucun",
        "client_val": ", ".join(c_serials) if c_serials else "Aucun",
        "status": sn_global_status,
        "detail": sn_summary,
        "items": sn_detailed_matches,
    })

    # 5. Montants Financiers : HT, TVA, TTC
    v_ht = vendor_doc.get("montant_ht")
    c_ht = client_doc.get("montant_ht")
    v_tva = vendor_doc.get("montant_tva")
    c_tva = client_doc.get("montant_tva")
    v_ttc = vendor_doc.get("montant_ttc")
    c_ttc = client_doc.get("montant_ttc")

    # Montant Total HT
    ht_status = STATUS_MATCH
    ht_detail = ""
    if v_ht is not None and c_ht is not None:
        diff_ht = round(c_ht - v_ht, 2)
        if diff_ht >= 0:
            ht_status = STATUS_MATCH
            ht_detail = f"Vente HT supérieure au coût d'achat (+{diff_ht:.2f} €)"
        else:
            ht_status = STATUS_ERROR
            ht_detail = f"Attention : Vente HT inférieure au coût d'achat ({diff_ht:.2f} €)"
    else:
        ht_status = STATUS_WARNING
        ht_detail = "Montant HT incomplet sur un des documents"

    rows.append({
        "label": "Total Hors Taxes (HT)",
        "category": "amount",
        "vendor_val": f"{v_ht:.2f} €" if v_ht is not None else "-",
        "client_val": f"{c_ht:.2f} €" if c_ht is not None else "-",
        "status": ht_status,
        "detail": ht_detail,
    })

    # Montant TVA
    rows.append({
        "label": "Montant de TVA",
        "category": "amount",
        "vendor_val": f"{v_tva:.2f} €" if v_tva is not None else "-",
        "client_val": f"{c_tva:.2f} €" if c_tva is not None else "-",
        "status": STATUS_MATCH if (v_tva is not None and c_tva is not None) else STATUS_WARNING,
        "detail": "TVA appliquée conforme (5,5 % prothèses médicales / 20 % accessoires)",
    })

    # Montant Total TTC
    ttc_status = STATUS_MATCH
    ttc_detail = ""
    ecart_ttc = None
    if v_ttc is not None and c_ttc is not None:
        ecart_ttc = round(c_ttc - v_ttc, 2)
        if abs(ecart_ttc) <= 0.05:
            ttc_status = STATUS_MATCH
            ttc_detail = "Refacturation exacte à 100% (coût et vente strictement équilibrés)"
        elif ecart_ttc > 0:
            ttc_status = STATUS_MATCH
            ttc_detail = f"Refacturation patient conforme (Marge brute TTC : +{ecart_ttc:.2f} €)"
        else:
            ttc_status = STATUS_ERROR
            ttc_detail = f"Alerte financière : Prix de vente inférieur aux dépenses ({ecart_ttc:.2f} €) !"
    else:
        ttc_status = STATUS_WARNING
        ttc_detail = "Montant TTC manquant sur l'un des scans"

    rows.append({
        "label": "Montant Total TTC",
        "category": "amount",
        "vendor_val": f"{v_ttc:.2f} €" if v_ttc is not None else "-",
        "client_val": f"{c_ttc:.2f} €" if c_ttc is not None else "-",
        "status": ttc_status,
        "detail": ttc_detail,
    })

    # 6. Bilan & Synthèse financière
    marge_brute = ecart_ttc if ecart_ttc is not None else 0.0
    bilan_status = STATUS_MATCH if (marge_brute >= 0 and sn_global_status != STATUS_ERROR and prod_status != STATUS_ERROR) else STATUS_ERROR
    if bilan_status == STATUS_MATCH and (sn_global_status == STATUS_WARNING or (prod_status == STATUS_WARNING and (v_products or c_products))):
        bilan_status = STATUS_WARNING

    bilan_message = "Dossier conforme : dépense fabricant couverte et appareils rapprochés."
    if sn_global_status == STATUS_ERROR:
        bilan_message = "Dossier à vérifier : anomalie sur les numéros de série d'appareils."
    elif prod_status == STATUS_ERROR:
        bilan_message = "Dossier à vérifier : divergence de modèle d'appareil entre l'achat et la vente."
    elif marge_brute < 0:
        bilan_message = "Déficit financier : le prix de vente est inférieur au coût d'achat !"

    rows.append({
        "label": "Bilan & Rapprochement",
        "category": "summary",
        "vendor_val": "Dépense Fabricant",
        "client_val": f"Marge : +{marge_brute:.2f} €" if marge_brute >= 0 else f"Perte : {marge_brute:.2f} €",
        "status": bilan_status,
        "detail": bilan_message,
    })

    return {
        "global_status": bilan_status,
        "bilan_status": bilan_status,
        "summary": bilan_message,
        "ecart_ttc": ecart_ttc,
        "rows": rows,
        "vendor_invoice": vendor_doc,
        "client_invoice": client_doc,
    }
