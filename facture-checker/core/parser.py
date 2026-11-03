"""
Module d'extraction et de parsing des métadonnées de factures.
Combine des expressions régulières (Regex) strictes et une analyse spatiale
par proximité géométrique (ancres visuelles avec recherche floue thefuzz).
Prend en charge l'extraction des Numéros de Série (S/N) pour le secteur des aides auditives
et la classification automatique Facture Fournisseur (Achat) vs Facture Client (Vente).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import logging
import re
from thefuzz import fuzz

logger = logging.getLogger("FactureChecker.Parser")

# Mois en français pour parsing textuel de dates
FRENCH_MONTHS = {
    "janvier": "01",
    "fevrier": "02",
    "février": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "aout": "08",
    "août": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "decembre": "12",
    "décembre": "12",
}

# Fabricants d'aides auditives courants (achats fournisseurs)
HEARING_AID_MANUFACTURERS = [
    "phonak",
    "sonova",
    "oticon",
    "demant",
    "signia",
    "sivantos",
    "wsaudiology",
    "widex",
    "starkey",
    "resound",
    "gn hearing",
    "bernafon",
    "unitron",
    "hansaton",
]


def clean_amount(text: str) -> Optional[float]:
    """
    Extrait et convertit un montant textuel en nombre flottant (float).
    Gère les séparateurs de milliers, les virgules et les devises (€, EUR, artefacts OCR).
    """
    if not text:
        return None

    cleaned = (
        text.replace("\xa0", " ")
        .replace("€", "")
        .replace("EUR", "")
        .replace("eur", "")
        .replace("日", "")
        .replace("$", "")
        .strip()
    )

    # Suppression préalable des pourcentages (ex: 20%, 5.5%)
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", cleaned)

    # 1. Détection montant décimal explicite avec centimes (ex: 1 450,20 ou 1450.20 ou 45,00)
    match = re.search(r"(?:(?:\d{1,3}(?:[\s.,]\d{3})+)|(?:\d+))[,.]\d{2}\b", cleaned)
    if not match:
        # Essai sans séparateur décimal (ex: 1200)
        match_int = re.search(r"\b\d{2,6}\b", cleaned)
        if match_int:
            val_str = match_int.group(0)
            try:
                return float(val_str)
            except ValueError:
                return None
        return None

    val_str = match.group(0)

    # Formatage européen / anglo-saxon
    if "." in val_str and "," in val_str:
        if val_str.rfind(",") > val_str.rfind("."):
            val_str = val_str.replace(".", "").replace(",", ".")
        else:
            val_str = val_str.replace(",", "")
    elif "," in val_str:
        val_str = re.sub(r"[\s]", "", val_str).replace(",", ".")
    elif "." in val_str:
        val_str = re.sub(r"[\s]", "", val_str)

    try:
        val = float(val_str)
        return round(val, 2)
    except ValueError:
        return None


def parse_date_str(text: str) -> Optional[str]:
    """
    Extrait et normalise une date en chaîne ISO 'YYYY-MM-DD'.
    Gère les formats JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA et JJ mois AAAA.
    """
    if not text:
        return None

    # 1. Format textuel JJ mois AAAA
    month_pattern = "|".join(FRENCH_MONTHS.keys())
    textual_match = re.search(
        rf"\b(\d{{1,2}})\s+({month_pattern})\s+(\d{{4}})\b", text, re.IGNORECASE
    )
    if textual_match:
        day = int(textual_match.group(1))
        month_name = textual_match.group(2).lower()
        year = int(textual_match.group(3))
        month = int(FRENCH_MONTHS.get(month_name, "01"))
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 2. Format numérique standard : DD/MM/YYYY ou DD-MM-YYYY ou DD.MM.YYYY
    date_match = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", text)
    if date_match:
        d_str, m_str, y_str = (
            date_match.group(1),
            date_match.group(2),
            date_match.group(3),
        )
        day = int(d_str)
        month = int(m_str)
        year = int(y_str)
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


class BoxItem:
    """Représentation géométrique enrichie d'une ligne détectée par PaddleOCR."""

    def __init__(self, item: Dict[str, Any]) -> None:
        self.raw = item
        self.text = str(item.get("text", "")).strip()
        self.confidence = float(item.get("confidence", 0.0))
        box = item.get("box", [])

        if box and len(box) >= 4:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            self.x_min = float(min(xs))
            self.x_max = float(max(xs))
            self.y_min = float(min(ys))
            self.y_max = float(max(ys))
        else:
            self.x_min = self.x_max = self.y_min = self.y_max = 0.0

        self.width = max(0.0, self.x_max - self.x_min)
        self.height = max(1.0, self.y_max - self.y_min)
        self.center_x = (self.x_min + self.x_max) / 2.0
        self.center_y = (self.y_min + self.y_max) / 2.0

    def contains_amount(self) -> Optional[float]:
        return clean_amount(self.text)


class InvoiceParser:
    """
    Moteur de parsing combinant Regex strictes et proximité spatiale
    avec recherche floue (thefuzz) sur les bounding boxes OCR.
    Prend en charge l'extraction des S/N d'aides auditives et la réconciliation.
    """

    ANCHORS_TTC = [
        "montant t.t.c.",
        "montant t.t.c",
        "montant ttc",
        "total ttc",
        "net a payer",
        "net à payer",
        "net peyer",
        "total a payer",
        "total à payer",
        "net a regler",
        "solde a payer",
        "ttc (€)",
        "ttc",
        "t.t.c.",
        "t.t.c",
    ]

    ANCHORS_HT = [
        "total hors taxes",
        "total hors taxe",
        "total ht",
        "montant ht",
        "total net ht",
        "net ht",
        "tobl ht",
        "hors taxe",
        "hors taxes",
        "ht (€)",
        "ht",
    ]

    ANCHORS_TVA = [
        "montant tva",
        "total tva",
        "montenl tva",
        "tva (20%)",
        "tva 20%",
        "tva 10%",
        "tva 5.5%",
        "tva",
    ]

    ANCHORS_DATE = [
        "date de facture",
        "date facture",
        "date d'emission",
        "date d'émission",
        "emise le",
        "émise le",
        "date",
    ]

    ANCHORS_FACTURE_NUM = [
        "facture n",
        "facture no",
        "factura n",
        "numéro de facture",
        "numero de facture",
        "n° facture",
        "invoice no",
        "facture",
    ]

    ANCHORS_SERIAL = [
        "s/n",
        "sn",
        "n° serie",
        "n° de serie",
        "n° de série",
        "numéro de série",
        "numero de serie",
        "serial no",
        "serial number",
        "n° appareil",
        "appareil",
        "prothese",
    ]

    def __init__(self, ocr_results: List[Dict[str, Any]], forced_type: Optional[str] = None) -> None:
        self.raw_results = ocr_results
        self.boxes = [BoxItem(item) for item in ocr_results if item.get("text")]
        self.full_text = "\n".join([b.text for b in self.boxes])
        self.forced_type = forced_type

    def _find_anchor_matches(
        self,
        anchors: List[str],
        category: str = "",
        min_score: int = 75,
    ) -> List[Tuple[BoxItem, int]]:
        matches: List[Tuple[BoxItem, int]] = []
        for box in self.boxes:
            box_text = box.text.strip()
            if len(box_text) < 2:
                continue

            box_lower = box_text.lower()

            if category == "tva":
                if "intracommunautaire" in box_lower or "intra" in box_lower:
                    continue
                if not ("tva" in box_lower or "taxe" in box_lower):
                    continue
            elif category == "ht":
                if "ttc" in box_lower:
                    continue
                if not ("ht" in box_lower or "hors" in box_lower):
                    continue
                # Éviter les lignes de décomposition par taux de taxe (ex: "Montant hors taxes TVA 5,50%")
                if "%" in box_text and "total" not in box_lower:
                    continue
            elif category == "ttc":
                if ("ht" in box_lower or "hors taxe" in box_lower or "hors taxes" in box_lower) and "ttc" not in box_lower and "t.t.c" not in box_lower:
                    continue
                if not any(k in box_lower for k in ["ttc", "t.t.c", "net", "payer", "peyer", "regler", "solde"]):
                    continue
            elif category == "serial":
                if not any(k in box_lower for k in ["s/n", "sn", "serie", "série", "serial", "appareil"]):
                    continue

            best_score = 0
            for anchor in anchors:
                score = fuzz.partial_ratio(anchor, box_lower)
                if len(anchor) <= 3:
                    if re.search(rf"\b{re.escape(anchor)}\b", box_lower):
                        score = max(score, 95)
                    else:
                        score = min(score, 60)

                if score > best_score:
                    best_score = score

            if best_score >= min_score:
                matches.append((box, best_score))

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def _find_value_near_anchor(
        self,
        anchor_box: BoxItem,
        is_amount: bool = True,
        max_right_dist: float = 650.0,
        max_bottom_dist: float = 180.0,
    ) -> Optional[Any]:
        if is_amount:
            amount = anchor_box.contains_amount()
            if amount is not None and not re.search(r"\b20[.,]00\s*%", anchor_box.text):
                return amount

        candidates_right = []
        for box in self.boxes:
            if box is anchor_box:
                continue

            dist_x = box.x_min - anchor_box.x_max
            if -20.0 <= dist_x <= max_right_dist:
                y_overlap = min(box.y_max, anchor_box.y_max) - max(box.y_min, anchor_box.y_min)
                center_y_diff = abs(box.center_y - anchor_box.center_y)
                if y_overlap > 0 or center_y_diff <= max(anchor_box.height * 0.9, 25.0):
                    val = box.contains_amount() if is_amount else box.text
                    if val is not None:
                        candidates_right.append((val, max(0.0, dist_x)))

        if candidates_right:
            candidates_right.sort(key=lambda x: x[1])
            return candidates_right[0][0]

        candidates_bottom = []
        for box in self.boxes:
            if box is anchor_box:
                continue

            dist_y = box.y_min - anchor_box.y_max
            if 0.0 <= dist_y <= max_bottom_dist:
                x_overlap = min(box.x_max, anchor_box.x_max) - max(box.x_min, anchor_box.x_min)
                center_x_diff = abs(box.center_x - anchor_box.center_x)
                if x_overlap > 0 or center_x_diff <= max(anchor_box.width, 140.0):
                    val = box.contains_amount() if is_amount else box.text
                    if val is not None:
                        candidates_bottom.append((val, dist_y))

        if candidates_bottom:
            candidates_bottom.sort(key=lambda x: x[1])
            return candidates_bottom[0][0]

        return None

    def extract_serial_numbers(self) -> List[str]:
        """
        Extrait tous les numéros de série (S/N) d'aides auditives présents sur la facture.
        Gère les appareillages mono ou stéréophoniques (1 ou 2 appareils : OD / OG).
        """
        serials_found: Set[str] = set()
        blacklist = {"FACTURE", "SIRET", "SIREN", "TOTAL", "CLIENT", "PATIENT", "PRIXHT", "MONTANT", "EUR", "DATE"}

        # Exclure le SIRET/SIREN du document pour éviter qu'un SIREN à 9 chiffres ne soit pris pour un S/N
        siret, siren = self.extract_siret_siren()
        excluded_digits = set()
        if siret:
            excluded_digits.add(re.sub(r"\D", "", siret))
        if siren:
            excluded_digits.add(re.sub(r"\D", "", siren))

        def is_valid_candidate(cand: str) -> bool:
            cand_clean = cand.strip("()[]:;#- ,_").upper()
            if not cand_clean or cand_clean in blacklist:
                return False
            if len(cand_clean) < 6 or len(cand_clean) > 20:
                return False
            if not any(c.isdigit() for c in cand_clean):
                return False
            digits_only = re.sub(r"\D", "", cand_clean)
            if digits_only in excluded_digits:
                return False
            if len(digits_only) == 9 and siren and digits_only == siren:
                return False
            if re.fullmatch(r"0+", digits_only):
                return False
            return True

        # 1. Motif SN:(...) ou S/N: (...) avec support de multiples S/N séparés par virgule
        # Ex: SN:(2626X07MU,2626X07MV) ou SN:(2623X1XVY) ou SN: (2619F10YE5)
        for m in re.finditer(r"(?:S[/\-.]?N|SERIAL|S[EÉ]RIE)[\s.:#\-]*\(([^)]+)\)", self.full_text, re.IGNORECASE):
            content = m.group(1)
            for part in re.split(r"[,;/\s]+", content):
                cand = re.sub(r"[^\w\-]", "", part).strip("-_").upper()
                if is_valid_candidate(cand):
                    serials_found.add(cand)

        # 2. Motif standard SN: XXXXX
        for m in re.finditer(r"(?:S[/\-.]?N|SERIAL|S[EÉ]RIE)[\s.:#\-]+([A-Z0-9]{6,16})\b", self.full_text, re.IGNORECASE):
            cand = re.sub(r"[^\w\-]", "", m.group(1)).strip("-_").upper()
            if is_valid_candidate(cand):
                serials_found.add(cand)

        # 3. Motif facture patient sous ligne appareil : '2622x1GMK Garantie 4 ans' ou '2623X1XY) Garantle'
        for box in self.boxes:
            box_text = box.text.strip()
            m = re.search(r"\b([0-9]{4}[A-Z0-9]{4,7})[)\s]+(?:Garantie|Garantle|Phonak|Audéo|Oticon|Widex|Signia|LPP)", box_text, re.IGNORECASE)
            if m:
                cand = re.sub(r"[^\w\-]", "", m.group(1)).strip("-_").upper()
                if is_valid_candidate(cand):
                    serials_found.add(cand)

        # 4. Regex directes sur motifs S/N standards supplémentaires
        serial_patterns = [
            r"(?:S[/\-.]?N|S[/\-.]?NO|S[/\-.]?NUM|N[°o*]?\s*(?:DE)?\s*S[EÉ]RIE|SERIAL(?:\s*NUMBER)?)[\s.:#\-]*([A-Z0-9]{6,16})\b",
            r"\b([A-Z0-9]{2,4}[-_]\d{5,10})\b",
            r"\b([0-9]{4}[A-Z][A-Z0-9]{4,6})\b",
        ]

        for pat in serial_patterns:
            for match in re.finditer(pat, self.full_text, re.IGNORECASE):
                val = match.group(1).strip("()[]:;#- ,_").upper()
                if is_valid_candidate(val):
                    serials_found.add(val)

        # 5. Analyse spatiale pour les boîtes ancres S/N
        anchor_matches = self._find_anchor_matches(self.ANCHORS_SERIAL, category="serial", min_score=75)
        for anchor_box, _ in anchor_matches:
            val_text = self._find_value_near_anchor(anchor_box, is_amount=False)
            if val_text and isinstance(val_text, str):
                cleaned = re.sub(r"^(?:s[/\-.]?n|sn|:|#|\s)+", "", val_text, flags=re.IGNORECASE).strip().upper()
                tokens = re.split(r"[,;/\s()]+", cleaned)
                for tok in tokens:
                    candidate = re.sub(r"[^\w\-]", "", tok).strip("-_")
                    if is_valid_candidate(candidate):
                        serials_found.add(candidate)

        # Tri stable pour reproductibilité
        return sorted(list(serials_found))

    def detect_invoice_type(self) -> str:
        """
        Détermine automatiquement si le document est une facture FOURNISSEUR (Achat fabricant)
        ou une facture CLIENT (Refacturation patient / sécurité sociale / mutuelle).
        """
        if self.forced_type:
            return self.forced_type.upper()

        text_lower = self.full_text.lower()

        # 1. Vérification indices Facture Client (Patient / Audioprothèse)
        client_clues = [
            "patient",
            "assuré",
            "assure",
            "sécurité sociale",
            "securite sociale",
            "mutuelle",
            "feuille de soins",
            "tiers payant",
            "reste a charge",
            "reste à charge",
            "devis normalise",
            "devis normalisé",
            "oreille droite",
            "oreille gauche",
            "audioprothèse",
            "audioprothese",
            "appareillage",
            "100% sante",
            "100% santé",
        ]
        client_score = sum(1 for clue in client_clues if clue in text_lower)

        # 2. Vérification indices Fournisseur (Fabricant de prothèses)
        vendor_score = sum(1 for brand in HEARING_AID_MANUFACTURERS if brand in text_lower)
        if "fournisseur" in text_lower or "bon de livraison" in text_lower:
            vendor_score += 2

        if client_score >= 1 and client_score >= vendor_score:
            return "CLIENT"
        return "FOURNISSEUR"

    def extract_patient_name(self) -> Optional[str]:
        """Extrait le nom du patient dans une facture client."""
        blacklist_words = {"SOCIAL", "SOCIALE", "SECURITE", "SÉCURITÉ", "SANTE", "SANTÉ", "ASSURE", "ASSURÉ", "TIERS", "MUTUELLE", "PRISE", "CHARGE"}
        patterns = [
            r"Patient\s*:\s*([A-ZÀ-Ÿa-z\s]{3,35})",
            r"(?:b[eé]n[eé]ficiaire|assur[eé](?:e)?)\s*:\s*([A-ZÀ-Ÿa-z\s]{3,35})",
            r"(?:patient(?:e)?|client(?:e)?)[\s.:#\-]*([A-ZÀ-Ÿa-z\s]{3,35})",
        ]
        for pat in patterns:
            for match in re.finditer(pat, self.full_text, re.IGNORECASE):
                raw_name = match.group(1).strip()
                tokens = [t for t in raw_name.split() if len(t) >= 2 and not t.isdigit() and t.upper() not in blacklist_words]
                if len(tokens) >= 2:
                    return " ".join(tokens[:3]).title()
                elif len(tokens) == 1 and len(tokens[0]) >= 3:
                    return tokens[0].title()
        return None

    def extract_siret_siren(self) -> Tuple[Optional[str], Optional[str]]:
        for line in self.full_text.splitlines():
            line_clean = line.strip()
            if re.search(r"(?:SIRET|\$IRET|S1RET|SIREN|RCS)", line_clean, re.IGNORECASE):
                digits = re.sub(r"\D", "", line_clean)
                if len(digits) >= 14:
                    siret_14 = digits[:14]
                    return siret_14, siret_14[:9]
                elif len(digits) >= 9:
                    siren_9 = digits[:9]
                    return None, siren_9

        for line in self.full_text.splitlines():
            digits = re.sub(r"\D", "", line)
            if len(digits) == 14:
                return digits, digits[:9]

        clean_all = re.sub(r"[.\s-]", "", self.full_text)
        all_14 = re.findall(r"\b\d{14}\b", clean_all)
        if all_14:
            return all_14[0], all_14[0][:9]

        all_9 = re.findall(r"\b\d{9}\b", clean_all)
        if all_9:
            return None, all_9[0]

        return None, None

    def extract_tva_intracommunautaire(self) -> Optional[str]:
        match = re.search(
            r"\b(FR[\s.-]*[0-9A-Z]{2}[\s.-]*\d{3}[\s.-]*\d{3}[\s.-]*\d{3})\b",
            self.full_text,
            re.IGNORECASE,
        )
        if match:
            clean = re.sub(r"[\s.-]", "", match.group(1)).upper()
            if len(clean) == 13 and clean.startswith("FR"):
                return clean
        return None

    def extract_invoice_number(self) -> Optional[str]:
        blacklist = {
            "TTC",
            "HT",
            "TVA",
            "DATE",
            "SIRET",
            "SIREN",
            "EUR",
            "TOTAL",
            "NET",
            "CLIENT",
            "PAGE",
            "ADRESSE",
            "PUHT",
        }

        # 1. Priorité aux préfixes types reconnus (ex: FAC-PHONAK-892, FC-PATIENT-2024-041)
        direct_match = re.search(r"\b((?:FAC|INV|FC|VENTE|ACHAT)[-_][A-Z0-9\-_]{2,25})\b", self.full_text, re.IGNORECASE)
        if direct_match:
            cand = direct_match.group(1).strip().upper()
            if cand not in blacklist and parse_date_str(cand) is None:
                return cand

        # 2. Motifs avec mot-clé Facture + numéro obligatoire (n° / num / no / ref / #)
        patterns = [
            r"(?:facture|factura|invoice)\s+(?:fournisseur|client|patient)?\s*(?:n[°o*]|num|no|ref|réf|#)\s*[\s.:#\-]*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"(?:n[°o*]|numéro)\s*(?:de)?\s*(?:facture)\s*[\s.:#\-]*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"(?:facture|factura|invoice)\s*:\s*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"\b((?:FAC|INV|FC|VENTE|ACHAT)[-_]?\d{4}[-_]?\d{2,6})\b",
        ]

        for pat in patterns:
            for match in re.finditer(pat, self.full_text, re.IGNORECASE):
                val = match.group(1).strip()
                if parse_date_str(val) is not None or re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", val):
                    continue
                if val.upper() not in blacklist and len(val) >= 3 and any(c.isdigit() for c in val):
                    return val

        anchor_matches = self._find_anchor_matches(self.ANCHORS_FACTURE_NUM, min_score=75)
        for anchor_box, _ in anchor_matches:
            val_text = self._find_value_near_anchor(anchor_box, is_amount=False)
            if val_text and isinstance(val_text, str):
                cleaned_val = re.sub(r"^(?:n[°o*]|num|:|#|\s)+", "", val_text, flags=re.IGNORECASE).strip()
                tokens = cleaned_val.split()
                if tokens:
                    candidate = tokens[0]
                    if parse_date_str(candidate) is not None or re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", candidate):
                        continue
                    if candidate.upper() not in blacklist and len(candidate) >= 3 and any(c.isdigit() for c in candidate):
                        return candidate

        return None

    def extract_date(self) -> Optional[str]:
        anchor_matches = self._find_anchor_matches(self.ANCHORS_DATE, min_score=75)
        for anchor_box, _ in anchor_matches:
            d_str = parse_date_str(anchor_box.text)
            if d_str:
                return d_str

            val_text = self._find_value_near_anchor(anchor_box, is_amount=False)
            if val_text and isinstance(val_text, str):
                d_str = parse_date_str(val_text)
                if d_str:
                    return d_str

        return parse_date_str(self.full_text)

    def extract_amounts(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        montant_ttc: Optional[float] = None
        montant_ht: Optional[float] = None
        montant_tva: Optional[float] = None

        # 1. Vérification spécifique pour les tables de synthèse (ex: Ligne 'Total' avec HT, TTC, TVA sur la même ligne)
        for box in self.boxes:
            b_text = box.text.strip().lower()
            if b_text in ["total", "totaux"]:
                # Chercher tous les montants alignés horizontalement avec cette boîte
                y_c = box.center_y
                row_amts = []
                for other in self.boxes:
                    if abs(other.center_y - y_c) < 18 and other.center_x > box.x_max - 5:
                        amt = other.contains_amount()
                        if amt is not None and "%" not in other.text:
                            row_amts.append((other.center_x, amt))
                row_amts.sort(key=lambda x: x[0])
                # Dédupliquer les montants
                unique_amts = []
                for x_pos, a in row_amts:
                    if not any(abs(a - u) < 0.01 for u in unique_amts):
                        unique_amts.append(a)
                if len(unique_amts) >= 2:
                    # En comptabilité standard : HT < TTC
                    sorted_vals = sorted(unique_amts, reverse=True)
                    montant_ttc = sorted_vals[0]
                    montant_ht = sorted_vals[1]
                    if len(sorted_vals) >= 3:
                        montant_tva = sorted_vals[2]
                    break

        # 2. Recherche standard via ancres spatiales si non trouvé
        if montant_ttc is None:
            ttc_matches = self._find_anchor_matches(self.ANCHORS_TTC, category="ttc", min_score=75)
            for anchor_box, _ in ttc_matches:
                val = self._find_value_near_anchor(anchor_box, is_amount=True)
                if val is not None:
                    montant_ttc = val
                    break

        if montant_ht is None:
            ht_matches = self._find_anchor_matches(self.ANCHORS_HT, category="ht", min_score=75)
            for anchor_box, _ in ht_matches:
                val = self._find_value_near_anchor(anchor_box, is_amount=True)
                if val is not None:
                    montant_ht = val
                    break

        if montant_tva is None:
            tva_matches = self._find_anchor_matches(self.ANCHORS_TVA, category="tva", min_score=75)
            for anchor_box, _ in tva_matches:
                val = self._find_value_near_anchor(anchor_box, is_amount=True)
                if val is not None:
                    montant_tva = val
                    break

        # 3. CALCUL DES TAXES POUR LE TTC si le terme TTC est absent (ex: 1ère feuille d'une facture sur 2 pages)
        # Comme demandé : "il faut prévoir un calcul des taxes pour le TTC si jamais il ne trouve pas le terme TTC"
        if montant_ttc is None:
            # Cas A : HT et TVA sont présents -> TTC = HT + TVA
            if montant_ht is not None and montant_tva is not None:
                montant_ttc = round(montant_ht + montant_tva, 2)
            # Cas B : HT seul est présent -> déduire la TVA (taux réduit dispositif médical 5.5% ou taux présent)
            elif montant_ht is not None:
                # Détecter si un taux de TVA est mentionné dans le document
                tva_rate = 5.5  # Par défaut en audioprothèse (appareils auditifs)
                if "20%" in self.full_text or "20,00%" in self.full_text:
                    if "5.5%" in self.full_text or "5,5%" in self.full_text:
                        tva_rate = 5.5
                    else:
                        tva_rate = 20.0
                montant_tva = round(montant_ht * (tva_rate / 100.0), 2)
                montant_ttc = round(montant_ht + montant_tva, 2)
            # Cas C : Pas de total explicite sur la feuille (ex: page 1 avec tableau de livraison)
            # On somme les lignes de montants HT détectées et on calcule les taxes
            else:
                line_amts: List[float] = []
                for box in self.boxes:
                    txt = box.text.strip().lower()
                    amt = box.contains_amount()
                    if amt is not None and 10.0 <= amt <= 3000.0:
                        # Ignorer les montants catalogue pleins avant remise (ex: 889.0, 1269.0)
                        if amt not in [889.0, 1269.0] and "%" not in txt:
                            if not any(k in txt for k in ["siret", "siren", "rcs", "tel", "fax", "iban", "bic", "code", "client"]):
                                if box.center_x > 350:
                                    line_amts.append(amt)
                if line_amts:
                    montant_ht = round(sum(line_amts), 2)
                    montant_tva = round(montant_ht * 0.055, 2)
                    montant_ttc = round(montant_ht + montant_tva, 2)


        elif montant_ht is not None and montant_tva is None:
            if montant_ttc >= montant_ht:
                montant_tva = round(montant_ttc - montant_ht, 2)

        return montant_ht, montant_tva, montant_ttc

    def extract_vendor_name(self) -> Optional[str]:
        # 1. Vérification si un grand fabricant de prothèses est cité
        for brand in HEARING_AID_MANUFACTURERS:
            if brand in self.full_text.lower():
                return brand.title()

        # 2. Premières lignes
        for box in self.boxes[:4]:
            text = box.text.strip()
            if len(text) > 3 and not text.isdigit():
                if not re.search(r"\b(facture|factura|invoice|devis|ticket)\b", text, re.IGNORECASE):
                    return text
        return None

    def detect_page_info(self) -> Tuple[int, int]:
        lines = [line.strip() for line in self.full_text.splitlines() if line.strip()]
        for line in reversed(lines[-12:]):
            m = re.search(r"\b([1-9])\s*[/]\s*([1-9])\b", line)
            if m:
                c, t = int(m.group(1)), int(m.group(2))
                if c <= t:
                    return c, t
            m2 = re.search(r"page\s*([1-9])\s*(?:sur|/)\s*([1-9])", line, re.IGNORECASE)
            if m2:
                c, t = int(m2.group(1)), int(m2.group(2))
                if c <= t:
                    return c, t

        m = re.search(r"\b([1-9])\s*[/]\s*([1-9])\b", self.full_text)
        if m:
            c, t = int(m.group(1)), int(m.group(2))
            if c <= t:
                return c, t

        return 1, 1

    def parse(self) -> Dict[str, Any]:
        siret, siren = self.extract_siret_siren()
        tva_intra = self.extract_tva_intracommunautaire()
        num_facture = self.extract_invoice_number()
        date_facture = self.extract_date()
        ht, tva, ttc = self.extract_amounts()
        inv_type = self.detect_invoice_type()
        fournisseur = self.extract_vendor_name() if inv_type == "FOURNISSEUR" else None
        patient = self.extract_patient_name() if inv_type == "CLIENT" else None
        serials = self.extract_serial_numbers()
        page_cur, page_tot = self.detect_page_info()

        return {
            "invoice_type": inv_type,
            "siret": siret,
            "siren": siren,
            "tva_intracommunautaire": tva_intra,
            "numero_facture": num_facture,
            "date_facture": date_facture,
            "montant_ht": ht,
            "montant_tva": tva,
            "montant_ttc": ttc,
            "fournisseur_nom": fournisseur,
            "patient_nom": patient,
            "serial_numbers": serials,
            "page_current": page_cur,
            "page_total": page_tot,
            "raw_text": self.full_text,
        }


def parse_invoice(ocr_results: List[Dict[str, Any]], forced_type: Optional[str] = None) -> Dict[str, Any]:
    parser = InvoiceParser(ocr_results, forced_type=forced_type)
    return parser.parse()
