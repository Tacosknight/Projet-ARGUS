"""
Module de post-traitement et correction heuristique des sorties OCR.
Spécialisé dans le domaine de l'audioprothèse :
- Normalisation robuste des numéros de série (S/N) avec suppression des espaces parasites
  et correction des confusions OCR fréquentes (ex: 'O' vs '0', 'l'/'I' vs '1', 'B' vs '8').
- Détection et correction des séparateurs décimaux omis sur les montants fiscaux (HT, TVA, TTC).
- Normalisation lexicale des abréviations fiscales (T.T.C, H.T., TVA) et des fabricants.
"""

import re
from typing import Any, Dict, List, Optional
from thefuzz import fuzz

# Fabricants reconnus pour réconciliation floue
KNOWN_MANUFACTURERS = [
    "Phonak",
    "Sonova",
    "Signia",
    "Widex",
    "WS Audiology",
    "Sivantos",
    "Oticon",
    "Bernafon",
    "Prodition",
    "Demant",
    "Philips",
    "Interacoustics",
    "Starkey",
    "GN Hearing",
    "ReSound",
    "Beltone",
    "Interton",
    "L'Atelier de l'Embout",
    "Unitron",
]


def is_phone_number(cand: str) -> bool:
    """
    Détermine si une chaîne correspond à un numéro de téléphone ou de fax
    (formats français et internationaux, avec ou sans séparateurs).
    Exemples détectés :
    - '02 43 28 15 10', '02.43.28.15.10', '02-43-28-15-10', '0243281510'
    - '01 42 89 10 12', '06 12 34 56 78', '07.98.76.54.32'
    - '+33 2 43 28 15 10', '+33243281510', '0033 1 42 89 10 12', '+33 (0)2 43 28 15 10'
    - Chaînes avec préfixes 'Tél', 'Tel', 'Tél.', 'Fax', 'Mobile', etc.
    """
    if not cand:
        return False

    clean = cand.strip()
    clean_lower = clean.lower()

    # 1. Présence explicite d'un indicateur de téléphonie ou fax
    if re.search(r"\b(?:t[eé]l|telephone|t[eé]l[eé]phone|fax|mob(?:ile)?|port(?:able)?|standard|hotline|contact)\b", clean_lower):
        return True

    # 2. Suppression des variantes '(0)' dans '+33 (0)2 ...'
    s_norm = re.sub(r"\(0\)", "", clean)

    # 3. Format international français (+33 ou 0033 suivi de 9 chiffres)
    digits_and_plus = re.sub(r"[^\d+]", "", s_norm)
    if re.fullmatch(r"(?:\+33|0033)[1-9]\d{8}", digits_and_plus):
        return True

    # Autres indicatifs internationaux européens courants (+32 Belgique, +41 Suisse, etc.)
    if re.fullmatch(r"(?:\+32|0032|\+41|0041|\+352|00352)[1-9]\d{7,9}", digits_and_plus):
        return True

    # 4. Format national français standard (10 chiffres commençant par 01 à 09)
    digits_only = re.sub(r"\D", "", s_norm)
    if len(digits_only) == 10 and re.fullmatch(r"0[1-9]\d{8}", digits_only):
        return True

    # Formats avec 9 ou 10 chiffres commençant par 0
    if re.fullmatch(r"0[1-9]\d{8,9}", digits_only):
        return True

    return False


def is_compact_date(cand: str) -> bool:
    """
    Détecte si une séquence de 8 chiffres correspond à une date calendrier valide
    (YYYYMMDD ou DDMMYYYY) comprise entre 2000 et 2035.
    """
    if not cand:
        return False
    digits = re.sub(r"\D", "", cand)
    if len(digits) != 8:
        return False

    # Format YYYYMMDD (2000-2035)
    y1 = int(digits[:4])
    m1 = int(digits[4:6])
    d1 = int(digits[6:8])
    if 2000 <= y1 <= 2035 and 1 <= m1 <= 12 and 1 <= d1 <= 31:
        return True

    # Format DDMMYYYY (2000-2035)
    d2 = int(digits[:2])
    m2 = int(digits[2:4])
    y2 = int(digits[4:8])
    if 2000 <= y2 <= 2035 and 1 <= m2 <= 12 and 1 <= d2 <= 31:
        return True

    return False


def clean_serial_number(sn_raw: str) -> str:
    """
    Nettoie et normalise un numéro de série d'aide auditive ou d'embout sur-mesure.
    - Élimine les faux positifs téléphoniques et coordonnées.
    - Élimine les espaces internes accidentels (ex: '934 534' -> '934534').
    - Corrige les confusions de lettres dans les blocs numériques (ex: '241O8923' -> '24108923').
    - Préserve l'intégrité des formats mixtes comme les embouts (ex: '250618GUAN1').
    """
    if not sn_raw:
        return ""

    if is_phone_number(sn_raw):
        return ""

    sn = sn_raw.strip()

    # 1. Vérification si format embout sur-mesure (ex: 250618GUAN1 ou 250618GUAN2)
    # 6 chiffres de date + 2-5 lettres initiales + 1 chiffre oreille
    m_embout = re.match(r"^(\d{6})([A-Za-z]{2,5})(\d{1,2})$", sn)
    if m_embout:
        return f"{m_embout.group(1)}{m_embout.group(2).upper()}{m_embout.group(3)}"

    # 2. Suppression des espaces internes entre chiffres (ex: "934 534" -> "934534")
    sn = re.sub(r"(?<=\d)\s+(?=\d)", "", sn)
    sn = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", sn)
    sn = re.sub(r"(?<=\d)\s+(?=[A-Za-z])", "", sn)

    # 3. Remplacement des caractères ambigus dans une séquence principalement numérique
    # Ex: 'O' majuscule ou 'o' minuscule pris pour un zéro
    # 'l' (L minuscule) ou 'I' (i majuscule) pris pour un '1'
    # 'S' ou 's' pris pour un '5'
    # 'B' pris pour un '8'
    # Seulement si entouré de chiffres ou au début/fin d'un bloc de 5+ chiffres
    digits_count = sum(1 for c in sn if c.isdigit())
    letters_count = sum(1 for c in sn if c.isalpha())

    if digits_count >= 4 and letters_count <= 2:
        # Substitutions contextuelles sûres
        # Lettre entourée de deux chiffres
        sn = re.sub(r"(?<=\d)[Oo](?=\d)", "0", sn)
        sn = re.sub(r"(?<=\d)[Il|](?=\d)", "1", sn)
        sn = re.sub(r"(?<=\d)[Ss](?=\d)", "5", sn)
        sn = re.sub(r"(?<=\d)[Bb](?=\d)", "8", sn)
        sn = re.sub(r"(?<=\d)[Zz](?=\d)", "2", sn)

        # Remplacement en fin de chaîne si précédé de 4+ chiffres (ex: 210984O -> 2109840)
        sn = re.sub(r"(?<=\d{4})[Oo]$", "0", sn)
        sn = re.sub(r"(?<=\d{4})[Il|]$", "1", sn)

        # Remplacement en début de chaîne si suivi de 4+ chiffres (ex: O210984 -> 0210984)
        sn = re.sub(r"^[Oo](?=\d{4})", "0", sn)
        sn = re.sub(r"^[Il|](?=\d{4})", "1", sn)

    # Nettoyage final des ponctuations résiduelles
    sn = sn.strip(".:,;-_/# ")
    if is_phone_number(sn) or is_compact_date(sn):
        return ""
    return sn.upper()


def normalize_amount_text(text: str) -> str:
    """
    Répare les montants fiscaux mal segmentés par l'OCR :
    - Détecte les centimes séparés par un espace au lieu d'une virgule (ex: '1 129 00 EUR' -> '1 129,00 EUR').
    - Répare les doubles séparateurs (ex: '1129,,00' -> '1129,00').
    """
    if not text:
        return ""

    s = text

    # Corriger les doubles virgules ou points uniquement dans les montants
    s = re.sub(r"(?<=\d)[,.]{2,}(?=\d)", ",", s)

    # Détection pattern: chiffres + espace + 2 chiffres (centimes) suivis de fin ou EUR/€
    # Ex: 'Total TTC 1129 00' ou 'Montant 414 00 EUR'
    def _sub_amount(m):
        suffix = (m.group(3) or "").strip()
        if suffix:
            return f"{m.group(1)},{m.group(2)} {suffix}"
        return f"{m.group(1)},{m.group(2)}"

    s = re.sub(
        r"(\b\d{1,5})\s+(\d{2})\s*(€|EUR|eur|Eur|\b)",
        _sub_amount,
        s,
    )

    # Répare les espaces avant la virgule (ex: '1129 ,00' -> '1129,00')
    s = re.sub(r"(\d+)\s+([,.])\s*(\d{2})", r"\1\2\3", s)

    return s.strip()


def normalize_fiscal_tokens(text: str) -> str:
    """
    Normalise les libellés fiscaux courants pour faciliter le repérage par ancres :
    - 'T.TC', 'TTC.', 'T.T.C' -> 'T.T.C.'
    - 'H.T', 'HT.', 'H. T.' -> 'H.T.'
    - 'T.V.A', 'TVA.' -> 'TVA'
    """
    if not text:
        return ""

    s = text
    # Remplacements ciblés insensibles à la casse
    s = re.sub(r"\b(?:TOTAL|MONTANT)\s+T\.?T\.?C\.?\b", "Total T.T.C.", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:TOTAL|MONTANT)\s+H\.?T\.?\b", "Total H.T.", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<!Total\s)(?<!Montant\s)\bT\.?T\.?C\.?\b", "T.T.C.", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<!Total\s)(?<!Montant\s)\bH\.?T\.?\b", "H.T.", s, flags=re.IGNORECASE)
    s = re.sub(r"\bT\.?V\.?A\.?\b", "TVA", s, flags=re.IGNORECASE)
    s = re.sub(r"\.{2,}", ".", s)

    return s

    return s


def clean_vendor_fuzzy(name_candidate: str) -> Optional[str]:
    """
    Rapproche un nom de fabricant brut extrait par l'OCR du nom canonique via fuzzy matching.
    Ex: 'Pbonak' -> 'Phonak', 'Wldex' -> 'Widex', 'Signia France' -> 'Signia'
    """
    if not name_candidate or len(name_candidate.strip()) < 3:
        return None

    clean = name_candidate.strip()
    best_match = None
    best_score = 0

    for m in KNOWN_MANUFACTURERS:
        s1 = fuzz.partial_ratio(m.lower(), clean.lower())
        s2 = fuzz.token_set_ratio(m.lower(), clean.lower())
        s3 = max((fuzz.ratio(m.lower(), tok.lower()) for tok in clean.split()), default=0)
        score = max(s1, s2, s3)
        if score > best_score and score >= 75:
            best_score = score
            best_match = m

    return best_match


def post_correct_ocr_boxes(boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Applique l'ensemble des corrections heuristiques sur une liste d'éléments OCR (boîtes spatiales).
    Retourne une nouvelle liste d'éléments avec les textes nettoyés et normalisés.
    """
    corrected: List[Dict[str, Any]] = []

    for item in boxes:
        raw_text = str(item.get("text", "")).strip()
        if not raw_text:
            continue

        # 1. Normalisation fiscale
        text_fisc = normalize_fiscal_tokens(raw_text)

        # 2. Normalisation des montants
        text_amt = normalize_amount_text(text_fisc)

        # Nouvel item avec texte corrigé
        new_item = dict(item)
        new_item["text"] = text_amt
        new_item["original_text"] = raw_text
        corrected.append(new_item)

    return corrected
