"""
Module de détection et d'assemblage automatique des factures multi-pages.
Permet d'unifier les factures sur plusieurs feuilles (ex: Page 1/2 avec liste des S/N
et Page 2/2 avec le récapitulatif des totaux fiscaux).
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import re
import logging

logger = logging.getLogger("FactureChecker.MultiPage")


def detect_pagination(text: str) -> Tuple[int, int]:
    """
    Détecte le numéro de page courante et le nombre total de pages dans le texte OCR.
    Retourne (page_actuelle, total_pages), par défaut (1, 1).
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 1, 1

    # 1. Vérification prioritaire dans les 10 dernières lignes (emplacement classique)
    for line in reversed(lines[-10:]):
        m = re.search(r"\b([1-9])\s*[/]\s*([1-9])\b", line)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            if cur <= tot:
                return cur, tot

        m2 = re.search(r"page\s*([1-9])\s*(?:sur|/)\s*([1-9])", line, re.IGNORECASE)
        if m2:
            cur, tot = int(m2.group(1)), int(m2.group(2))
            if cur <= tot:
                return cur, tot

        # Si OCR a omis le slash (ex: "22" ou "2 2" ou "12" sur la fin du document)
        if len(line) <= 4:
            m_short = re.match(r"^([1-9])\s*([1-9])$", line)
            if m_short:
                cur, tot = int(m_short.group(1)), int(m_short.group(2))
                if cur <= tot and tot <= 5:
                    return cur, tot

    # 2. Recherche générale dans tout le document
    m = re.search(r"\b([1-9])\s*[/]\s*([1-9])\b", text)
    if m:
        cur, tot = int(m.group(1)), int(m.group(2))
        if cur <= tot:
            return cur, tot

    m2 = re.search(r"page\s*([1-9])\s*(?:sur|/)\s*([1-9])", text, re.IGNORECASE)
    if m2:
        cur, tot = int(m2.group(1)), int(m2.group(2))
        if cur <= tot:
            return cur, tot

    return 1, 1


def are_pages_of_same_invoice(doc_a: Dict[str, Any], doc_b: Dict[str, Any]) -> bool:
    """
    Détermine si deux pages scannées appartiennent à la même facture multi-pages.
    Critères :
    - Même numéro de facture (si présent sur les deux).
    - Même tiers / fabricant (ex: Phonak) avec pagination complémentaire (ex: 1/2 et 2/2).
    - Même client / même adresse / livraisons cohérentes.
    """
    num_a = doc_a.get("numero_facture")
    num_b = doc_b.get("numero_facture")

    # Critère direct : même numéro de facture
    if num_a and num_b and str(num_a).strip() == str(num_b).strip():
        return True

    # Récupération pagination (avec fallback automatique sur le texte OCR)
    p_a = doc_a.get("page_current")
    tot_a = doc_a.get("page_total")
    if p_a is None or tot_a is None or (p_a == 1 and tot_a == 1):
        p_a, tot_a = detect_pagination(doc_a.get("raw_text", ""))

    p_b = doc_b.get("page_current")
    tot_b = doc_b.get("page_total")
    if p_b is None or tot_b is None or (p_b == 1 and tot_b == 1):
        p_b, tot_b = detect_pagination(doc_b.get("raw_text", ""))

    type_a = (doc_a.get("invoice_type") or "FOURNISSEUR").upper()
    type_b = (doc_b.get("invoice_type") or "FOURNISSEUR").upper()

    if type_a == type_b:
        fourn_a = (doc_a.get("fournisseur_nom") or "").strip().lower()
        fourn_b = (doc_b.get("fournisseur_nom") or "").strip().lower()
        same_vendor = bool(fourn_a and fourn_b and fourn_a == fourn_b)

        raw_a = doc_a.get("raw_text", "").lower()
        raw_b = doc_b.get("raw_text", "").lower()
        common_tokens = ["phoneme", "phonak", "oticon", "signia", "widex", "sonova", "coulaines"]
        token_matches = sum(1 for tok in common_tokens if tok in raw_a and tok in raw_b)

        if same_vendor or token_matches >= 2:
            # Pagination complémentaire explicite (ex: 1/2 et 2/2)
            if (tot_a > 1 or tot_b > 1) and p_a != p_b:
                return True
            if (p_a == 1 and p_b == 2) or (p_a == 2 and p_b == 1):
                return True
            # Si l'un est la première page (sans totaux récapitulatifs) et l'autre contient le récapitulatif
            has_totals_a = ("total hors taxes" in raw_a or "montant t.t.c" in raw_a) and ("total" in raw_a)
            has_totals_b = ("total hors taxes" in raw_b or "montant t.t.c" in raw_b) and ("total" in raw_b)
            if (has_totals_a and not has_totals_b) or (has_totals_b and not has_totals_a):
                return True

    return False


def consolidate_pages(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fusionne plusieurs pages d'une même facture en un document unique consolidé :
    - Agrégation de tous les numéros de série (S/N) sans doublon.
    - Sélection des totaux officiels finaux (généralement sur la dernière page).
    - Préservation du numéro de facture et de la date.
    - Traçabilité des fichiers sources.
    """
    if not pages:
        raise ValueError("Aucune page à consolider.")

    # Trier par numéro de page
    sorted_pages = sorted(pages, key=lambda p: p.get("page_current", 1))

    # Document consolidé basé sur la première page pour les métadonnées
    p_first = sorted_pages[0]
    p_last = sorted_pages[-1]

    # Numéro de facture : prendre le premier non-nul
    numero_facture = None
    for p in sorted_pages:
        if p.get("numero_facture"):
            numero_facture = p["numero_facture"]
            break

    # Date : prendre la première non-nulle
    date_facture = None
    for p in sorted_pages:
        if p.get("date_facture"):
            date_facture = p["date_facture"]
            break

    # Tiers / Fournisseur
    fournisseur_nom = None
    for p in sorted_pages:
        if p.get("fournisseur_nom"):
            fournisseur_nom = p["fournisseur_nom"]
            break

    # Patient
    patient_nom = None
    for p in sorted_pages:
        if p.get("patient_nom"):
            patient_nom = p["patient_nom"]
            break

    # Type
    invoice_type = p_first.get("invoice_type") or "FOURNISSEUR"

    # SIRET / TVA
    siret = next((p.get("siret") for p in sorted_pages if p.get("siret")), None)
    siren = next((p.get("siren") for p in sorted_pages if p.get("siren")), None)
    tva_intra = next((p.get("tva_intracommunautaire") for p in sorted_pages if p.get("tva_intracommunautaire")), None)

    # Fusion des numéros de série
    all_serials: Set[str] = set()
    for p in sorted_pages:
        s_list = p.get("serial_numbers") or []
        for s in s_list:
            if s and str(s).strip():
                all_serials.add(str(s).strip().upper())

    # Totaux financiers :
    # Si la dernière page contient un total explicite (HT et TTC), on prend ces totaux officiels certifiés
    montant_ht = None
    montant_tva = None
    montant_ttc = None

    for p in reversed(sorted_pages):
        p_ttc = p.get("montant_ttc")
        p_ht = p.get("montant_ht")
        if p_ttc is not None and p_ht is not None and p_ttc >= 100.0:
            montant_ht = p_ht
            montant_ttc = p_ttc
            montant_tva = p.get("montant_tva")
            if montant_ttc and montant_ht and (montant_tva is None or abs(montant_ht + (montant_tva or 0) - montant_ttc) > 0.05):
                montant_tva = round(montant_ttc - montant_ht, 2)
            break

    # Si aucun total global certifié suffisant n'est trouvé, sommer les montants des pages
    if montant_ttc is None or montant_ttc < 100.0:
        sub_ht = sum((p.get("montant_ht") or 0.0) for p in sorted_pages if (p.get("montant_ht") or 0.0) >= 10.0)
        sub_tva = sum((p.get("montant_tva") or 0.0) for p in sorted_pages)
        if sub_ht > 0:
            montant_ht = round(sub_ht, 2)
            montant_tva = round(sub_tva if sub_tva > 0 else montant_ht * 0.055, 2)
            montant_ttc = round(montant_ht + montant_tva, 2)


    # Fichiers sources combinés
    filenames = [p.get("filename") for p in sorted_pages if p.get("filename")]
    combined_filename = " + ".join(filenames) if filenames else "facture_consolidee"
    if len(sorted_pages) > 1:
        combined_filename += f" ({len(sorted_pages)} pages)"

    # Texte brut concaténé
    raw_texts = []
    for idx, p in enumerate(sorted_pages, 1):
        txt = p.get("raw_text", "").strip()
        if txt:
            raw_texts.append(f"--- PAGE {idx}/{len(sorted_pages)} ---\n{txt}")
    combined_raw_text = "\n\n".join(raw_texts)

    pages_numbers = [p.get("page_current", 1) for p in sorted_pages]
    total_pages_declared = max((p.get("page_total", 1) for p in sorted_pages), default=len(sorted_pages))

    consolidated = {
        "filename": combined_filename,
        "invoice_type": invoice_type,
        "siret": siret,
        "siren": siren,
        "numero_facture": numero_facture,
        "date_facture": date_facture,
        "montant_ht": montant_ht,
        "montant_tva": montant_tva,
        "montant_ttc": montant_ttc,
        "tva_intracommunautaire": tva_intra,
        "fournisseur_nom": fournisseur_nom,
        "patient_nom": patient_nom,
        "serial_numbers": sorted(list(all_serials)),
        "raw_text": combined_raw_text,
        "is_multipage": len(sorted_pages) > 1,
        "pages_count": len(sorted_pages),
        "page_numbers": pages_numbers,
        "page_total": total_pages_declared,
        "is_complete": len(pages_numbers) >= total_pages_declared,
    }

    logger.info(
        "Consolidation réussie de %d page(s) -> Facture '%s' | S/N total : %s | TTC : %s €",
        len(sorted_pages),
        numero_facture,
        consolidated["serial_numbers"],
        montant_ttc,
    )

    return consolidated
