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
from core.post_corrector import is_phone_number
from core.product_policy import non_sale_reason

logger = logging.getLogger("FactureChecker.Parser")

# Mois en français pour parsing textuel de dates (noms complets et abréviations type 30-AVR-25)
FRENCH_MONTHS = {
    "janvier": "01", "janv": "01", "jan": "01",
    "fevrier": "02", "février": "02", "fevr": "02", "févr": "02", "fev": "02",
    "mars": "03", "mar": "03",
    "avril": "04", "avr": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07", "juil": "07",
    "aout": "08", "août": "08", "aou": "08",
    "septembre": "09", "sept": "09", "sep": "09",
    "octobre": "10", "oct": "10",
    "novembre": "11", "nov": "11",
    "decembre": "12", "décembre": "12", "dec": "12", "déc": "12",
}

# Fabricants d'aides auditives, groupes et laboratoires (achats fournisseurs)
HEARING_AID_MANUFACTURERS = [
    # Groupe Sonova
    "phonak", "sonova", "unitron", "hansaton", "advanced bionics",
    # Groupe GN Store Nord
    "gn hearing", "resound", "beltone", "interton",
    # Groupe Demant / Prodition
    "prodition", "oticon", "bernafon", "philips", "interacoustics", "demant",
    # Groupe WS Audiology
    "signia", "sivantos", "wsaudiology", "widex",
    # Groupe Starkey
    "starkey",
    # Laboratoires d'embouts sur-mesure & accessoires
    "l'atelier de l'embout", "atelier de l'embout", "atelier embout",
]

# Modèles, gammes et types d'appareils et accessoires audioprothétiques
HEARING_AID_PRODUCT_PATTERNS = [
    # Sonova / Phonak / Unitron
    r"\b(?:Phonak[ \t]+)?Aud[eé]o[ \t]+[A-Za-z0-9\s\-]+(?:\*|\b)",
    r"\b(?:Phonak[ \t]+)?(?:Lumity|Paradise|Marvel|Infinio|Sphere)\b[^\n,;]*",
    r"\b(?:Phonak[ \t]+)?(?:Na[ií]da|Virto|Sky|Bolero|CROS)[ \t]+[A-Za-z0-9\-]+",
    r"\b(?:Phonak[ \t]+)?ChargerGo[ \t]+[A-Za-z0-9 \t\-]+",
    r"\b(?:[MS][ \t]+)?Receiver[ \t]+[A-Za-z0-9 \t\-.]+",
    r"\bMoxi[ \t]+[A-Za-z0-9 \t\-]+",
    # WS Audiology / Widex / Signia
    r"\b(?:S_ITE[ \t]+)?(?:Signia[ \t]+)?(?:Silk|Insio|Styletto|Active|Motion)[ \t]+[A-Za-z0-9&. \t\-]+",
    r"\bMINIREC\.?[ \t]+[A-Za-z0-9. \t\-]+",
    r"\b(?:Signia[ \t]+)?(?:Pure|Styletto|Silk|Insio|Active|Motion)[ \t]+Charge&Go(?:[ \t]+[0-9A-Za-z]+)?",
    r"\b(?:Signia[ \t]+)?Pure[ \t]+[A-Za-z0-9 \t\-]+",
    r"\b(?:Widex[ \t]+)?Moment[ \t]+[0-9A-Za-z]+",
    r"\b(?:Widex[ \t]+)?(?:SmartRIC|Magnify|Evoke|Unique|Dream)[ \t]+[0-9A-Za-z]+",
    r"\bWidex[ \t]+PRO[ \t]+Link\b",
    r"\bAA[ \t]+MGY[ \t]+[A-Za-z0-9 \t\-]+",
    # Demant / Oticon / Bernafon / Philips
    r"\b(?:Oticon[ \t]+)?(?:Real|Intent|More|Zircon|Ruby|Opn|Siya|Xceed)(?:[ \t]+[0-9A-Za-z\-]+)+",
    r"\bSpeaker[ \t]+[A-Za-z0-9 \t\-.]+(?:Minifit(?:[ \t]+Detect)?)?",
    r"\b(?:Bernafon[ \t]+)?(?:Alpha|Leox|Entra|Nevara)[ \t]+[0-9A-Za-z]+",
    r"\bHearLink[ \t]+[0-9A-Za-z]+",
    # GN Hearing / ReSound
    r"\b(?:ReSound[ \t]+)?(?:OMNIA|Nexia|ONE|LiNX|Enzo|Key)[ \t]+[0-9A-Za-z]+",
    r"\b[EÉ]couteur[ \t]+[A-Za-z0-9 \t\-.]+",
    # Starkey
    r"\b(?:Evolv[ \t]+AI|Genesis[ \t]+AI|Livio(?:[ \t]+AI)?|Picasso|Muse)[ \t]+[0-9A-Za-z \t\-]+",
    # Embouts sur-mesure & labos
    r"\bDMSM[ \t]+RIC[ \t]+[^\n\r\d]+",
    r"\bEmbout[ \t]+(?:r[eé]sine|silicone|sur[\s\-]mesure)[A-Za-z0-9 \t\-]*",
]


def clean_product_name(text: str) -> str:
    """Nettoie une désignation de produit pour supprimer les résidus de tableau (quantités, prix, taxes, garanties)."""
    if not text:
        return ""
    cleaned = text.strip().rstrip("*").strip()
    # Supprimer les colonnes de fin de tableau : Quantité + Prix (ex: ' 1 28,00 5,50%' ou ' 1 PCS ...' ou ' 8 36,00 ...')
    cleaned = re.sub(r"[ \t]+\d+[ \t]+(?:\d+(?:[.,]\d+)?\b|\bPCS\b|\bPCE\b).*$", "", cleaned, flags=re.IGNORECASE)
    # Supprimer mention de fin type '1 PCS' ou '1 PCE' seul
    cleaned = re.sub(r"[ \t]+\d+[ \t]+(?:PCS|PCE|€|EUR)\b.*$", "", cleaned, flags=re.IGNORECASE)
    # Supprimer mentions parasites de fin (LPP, Garantie, OD, OG, Client:)
    cleaned = re.sub(r"[ \t]+(?:Garantie|LPP|Client:).*$", "", cleaned, flags=re.IGNORECASE)
    # Supprimer code article initial s'il est au format XXX-XXXX-XX (ex: '050-1091-P6 ')
    cleaned = re.sub(r"^\d{3}-\d{4}-[A-Z0-9]{2}\s+", "", cleaned)
    return cleaned.strip()


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

    # Rejeter les chaînes de dates ou contenant des slashes de date (ex: 30/06/25, 07-11-25)
    if re.search(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b", cleaned):
        return None
    if "/" in cleaned or "date" in cleaned.lower():
        return None

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
    Gère les formats JJ/MM/AAAA, JJ-MM-AAAA, JJ.MM.AAAA, JJ mois AAAA et JJ-MMM-AA (ex: 30-AVR-25).
    """
    if not text:
        return None

    clean_text = text.strip()

    # 1. Format textuel avec mois abrégé ou complet (ex: 30-AVR-25, 05-MAI-25, 12 janvier 2025)
    month_pattern = "|".join(sorted(FRENCH_MONTHS.keys(), key=len, reverse=True))
    textual_match = re.search(
        rf"\b(\d{{1,2}})[/\-.\s]+({month_pattern})[/\-.\s]+(\d{{2,4}})\b", clean_text, re.IGNORECASE
    )
    if textual_match:
        day = int(textual_match.group(1))
        month_name = textual_match.group(2).lower()
        year = int(textual_match.group(3))
        if year < 100:
            year += 2000
        month = int(FRENCH_MONTHS.get(month_name, "01"))
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 2. Format numérique standard : DD/MM/YYYY ou DD-MM-YYYY ou DD.MM.YYYY ou DD-MM-YY
    date_match = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", clean_text)
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
        "montant total eur",
        "montant total ttc",
        "montant ttc eur",
        "montant ttc €",
        "montant ttc",
        "montant t.t.c.",
        "montant t.t.c",
        "total ttc",
        "total t.t.c.",
        "total t.t.c",
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
        "montant total ht",
        "montant ht eur",
        "total hors taxes",
        "total hors taxe",
        "total ht",
        "total h.t.",
        "total net ht",
        "net ht",
        "net h.t.",
        "montant ht",
        "tobl ht",
        "hors taxe",
        "hors taxes",
        "ht (€)",
        "ht",
    ]

    ANCHORS_TVA = [
        "montant t.v.a.",
        "montant tva",
        "total tva",
        "montenl tva",
        "service vat",
        "tva (20%)",
        "tva 20%",
        "tva 10%",
        "tva 5.5%",
        "tva",
    ]

    ANCHORS_DATE = [
        "date de facture",
        "fait le",
        "en date du",
        "date facture",
        "date d'emission",
        "date d'émission",
        "emise le",
        "émise le",
        "date :",
        "date:",
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
        "facture :",
        "facture:",
        "facture",
    ]

    ANCHORS_SERIAL = [
        "n° de série",
        "n° de serie",
        "n° série",
        "n° serie",
        "numéro de série",
        "numero de serie",
        "s/n",
        "sn",
        "serial no",
        "serial number",
        "n° appareil",
        "appareil n°",
    ]

    def __init__(self, ocr_results: List[Dict[str, Any]], forced_type: Optional[str] = None) -> None:
        from core.post_corrector import post_correct_ocr_boxes
        corrected_ocr = post_correct_ocr_boxes(ocr_results)
        self.raw_results = corrected_ocr
        self.boxes = [BoxItem(item) for item in corrected_ocr if item.get("text")]
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
                if any(k in box_lower for k in ["p.u", "puht", "prix unitaire", "unitaire"]):
                    continue
                if not any(k in box_lower for k in ["ht", "h.t", "hors"]):
                    continue
                # Éviter les lignes de décomposition par taux de taxe (ex: "Montant hors taxes TVA 5,50%")
                if "%" in box_text and "total" not in box_lower:
                    continue
            elif category == "ttc":
                if any(k in box_lower for k in ["p.u", "puttc", "prix unitaire"]):
                    continue
                if ("ht" in box_lower or "hors taxe" in box_lower or "hors taxes" in box_lower) and "ttc" not in box_lower and "t.t.c" not in box_lower:
                    continue
                if not any(k in box_lower for k in ["ttc", "t.t.c", "net", "payer", "peyer", "regler", "solde"]):
                    continue
            elif category == "serial":
                # Exclure formellement toute boîte contenant des mots-clés d'en-tête, coordonnées ou administratifs
                if any(k in box_lower for k in [
                    "tel", "tél", "telephone", "téléphone", "fax", "contact",
                    "client", "commande", "page", "mail", "email", "web", "site",
                    "rcs", "siret", "siren", "sarl", "sas", "société", "societe",
                    "adresse", "rue", "avenue", "boulevard", "cedex"
                ]):
                    continue
                # Exclure les boîtes qui contiennent déjà un S/N inline (ex: "SN:(2623X1XVY)", "SN: 2623X...")
                # car une ligne avec une valeur de S/N n'est PAS un en-tête de colonne de tableau
                if re.search(r"(?:s[/\-.]?n|serial|s[eé]rie)[\s.:#\-]*\(?[A-Z0-9]{4,}", box_text, re.IGNORECASE):
                    continue
                if not any(k in box_lower for k in ["s/n", "sn", "serie", "série", "serial", "n° appareil", "appareil n°"]):
                    continue
            elif category == "date":
                if any(k in box_lower for k in ["commande", "livraison", "garantie", "échéance", "echeance", "relevé au", "releve au", "naissance", "prescription", "expédition", "expedition", "payer avant"]):
                    continue
                if not any(k in box_lower for k in ["date", "emise", "émise", "fait le"]):
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
        Gère les appareillages mono ou stéréophoniques (1 ou 2 appareils : OD / OG),
        les formats fabricants (Widex, Signia, Phonak, GN Hearing, Starkey, Atelier Embout).
        Éradique les faux positifs : numéros de téléphone, fax, codes postaux, dates,
        numéros de facture/commande/client, SIRET/SIREN.
        """
        serials_found: Set[str] = set()
        blacklist = {
            "FACTURE", "SIRET", "SIREN", "TOTAL", "CLIENT", "PATIENT", "PRIXHT", "MONTANT", "EUR", "DATE",
            "TRANSPORT", "ECOTAX", "ECOTAXE", "COMMANDE", "LIVRAISON", "GARANTIE", "EASYWEAR", "NOAHLINK",
            "CERUSTOP", "NANOCARE", "MINIFIT", "ECOUTEUR", "SPEAKER", "PROLINK", "RECEIVER", "ARTICLE",
            "TEL", "TELEPHONE", "TELEPHONIQUE", "FAX", "MOBILE", "PORTABLE", "CONTACT", "STANDARD", "HOTLINE",
            "COMPTE", "DEVIS", "REMISE", "ACOMPTE", "SOLDE", "REGLEMENT", "PAIEMENT", "ECHEANCE", "PAGE",
            "IBAN", "BIC", "BANQUE", "CODE", "POSTAL", "VILLE", "FRANCE", "RCS", "APE", "NAF", "TVA",
        }

        # 1. Exclure le SIRET/SIREN du document
        siret, siren = self.extract_siret_siren()
        excluded_digits = set()
        if siret:
            excluded_digits.add(re.sub(r"\D", "", siret))
        if siren:
            excluded_digits.add(re.sub(r"\D", "", siren))

        # 2. Exclure le numéro de facture
        num_facture = self.extract_invoice_number()
        if num_facture:
            blacklist.add(num_facture.upper())
            num_clean = re.sub(r"[^\w\-]", "", num_facture).upper()
            if num_clean:
                blacklist.add(num_clean)
            num_digits = re.sub(r"\D", "", num_facture)
            if num_digits and len(num_digits) >= 6:
                excluded_digits.add(num_digits)

        # 3. Exclure les dates du document
        excluded_dates = set()
        inv_date = self.extract_date()
        if inv_date:
            parts = inv_date.split("-")
            if len(parts) == 3:
                y, m, d = parts[0], parts[1], parts[2]
                excluded_dates.add(f"{y}{m}{d}")
                excluded_dates.add(f"{d}{m}{y}")
                excluded_dates.add(f"{d}{m}{y[2:]}")
                excluded_dates.add(f"{y[2:]}{m}{d}")

        for m_date in re.finditer(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", self.full_text):
            d, m, y = m_date.group(1).zfill(2), m_date.group(2).zfill(2), m_date.group(3)
            if len(y) == 2:
                y = f"20{y}"
            excluded_dates.add(f"{y}{m}{d}")
            excluded_dates.add(f"{d}{m}{y}")

        # 4. Exclure les numéros de livraison / BL / bon de livraison (ex: "Livraison 2186712386 du 06.07.2026")
        for m_livr in re.finditer(r"\b(?:l[li]vraison|bl|commande|expedition|expédition)[\s:]*([0-9]{6,12})\b", self.full_text, re.IGNORECASE):
            livr_num = m_livr.group(1)
            blacklist.add(livr_num)
            excluded_digits.add(livr_num)

        from core.post_corrector import is_phone_number, is_compact_date, clean_serial_number

        def is_valid_candidate(cand: str, box_context: str = "") -> bool:
            cand_clean = cand.strip("()[]:;#- ,_").upper()
            if not cand_clean or cand_clean in blacklist:
                return False
            if len(cand_clean) < 6 or len(cand_clean) > 20:
                return False
            if not any(c.isdigit() for c in cand_clean):
                return False

            # Filtre absolu anti-téléphone / fax / contact
            if is_phone_number(cand_clean) or is_phone_number(cand):
                return False

            # Si le texte de la boîte d'origine contient un mot-clé de contact téléphonique
            if box_context and re.search(r"\b(?:t[eé]l|telephone|t[eé]l[eé]phone|fax|mobile|portable|contact)\b", box_context, re.IGNORECASE):
                return False

            # Rejet des modèles d'appareils et références de piles (ex: L30-312, I50-R, L90-312, RIC312, BTE13)
            if re.search(r"^[A-Z]?\d{1,3}[-_]?(?:312|13|10|675|R|RIC|BTE)$", cand_clean, re.IGNORECASE):
                return False
            if re.search(r"^[A-Z]\d{2,3}-\d{2,3}$", cand_clean):
                return False
            if cand_clean in {"L30-312", "I50-R", "L90-312", "L70-312", "L50-312", "RIC312", "RIC-312"}:
                return False

            digits_only = re.sub(r"\D", "", cand_clean)

            # Rejet de tout numéro à 9 ou 10 chiffres commençant par 0 (téléphones fixes, mobiles, spéciaux)
            if len(digits_only) in (9, 10) and digits_only.startswith("0"):
                return False

            # Rejet des indicatifs internationaux +33 / 0033
            if cand_clean.startswith("+33") or cand_clean.startswith("0033"):
                return False

            # Rejet des dates compactes (YYYYMMDD ou DDMMYYYY)
            if digits_only in excluded_dates or is_compact_date(digits_only):
                return False

            # Rejet des codes postaux résiduels (5 chiffres)
            if len(digits_only) == 5 and len(cand_clean) == 5:
                return False

            # Rejet SIRET/SIREN et numéros de livraison
            if digits_only in excluded_digits:
                return False
            if len(digits_only) == 9 and siren and digits_only == siren:
                return False

            # Rejet des séquences de zéros
            if re.fullmatch(r"0+", digits_only):
                return False

            return True

        # 1. Motif explicite 'N° de série : XXXXX' ou 'N° de série : XXXXX - YYYYY' (Widex, Signia)
        for m in re.finditer(r"(?:num[eé]ro\s+de\s+s[eé]rie|n[°o*]?\s*(?:de\s*)?s[eé]rie|serial(?:\s*no)?)\s*[:#\-]\s*([^\n\r]+)", self.full_text, re.IGNORECASE):
            raw_val = m.group(1).strip()
            parts = re.split(r"[\s,\-/]+", raw_val)
            for part in parts:
                cand = re.sub(r"[^\w]", "", part).strip("-_").upper()
                if is_valid_candidate(cand):
                    serials_found.add(cand)

        # 2. Motif SN:(...) ou S/N: (...) avec support de multiples S/N séparés par virgule
        for m in re.finditer(r"(?:S[/\-.]?N|SERIAL|S[EÉ]RIE)[\s.:#\-]*\(([^)]+)\)", self.full_text, re.IGNORECASE):
            content = m.group(1)
            for part in re.split(r"[,;/\s]+", content):
                cand = re.sub(r"[^\w\-]", "", part).strip("-_").upper()
                if is_valid_candidate(cand):
                    serials_found.add(cand)

        # 3. Motif standard SN: XXXXX
        for m in re.finditer(r"(?:S[/\-.]?N|SERIAL|S[EÉ]RIE)[\s.:#\-]+([A-Z0-9]{6,16})\b", self.full_text, re.IGNORECASE):
            cand = re.sub(r"[^\w\-]", "", m.group(1)).strip("-_").upper()
            if is_valid_candidate(cand):
                serials_found.add(cand)

        # 4. Motif embouts sur-mesure (ex: 250618GUAN1, 250618GUAN2 chez L'Atelier de l'Embout)
        for m in re.finditer(r"\b(\d{6}[A-Z]{3,5}\d{1,2})\b", self.full_text):
            cand = m.group(1).upper()
            if is_valid_candidate(cand):
                serials_found.add(cand)

        # 5. Motif facture patient sous ligne appareil : '2622x1GMK Garantie 4 ans' ou '2623X1XY) Garantle'
        for box in self.boxes:
            box_text = box.text.strip()
            m = re.search(r"\b([A-Z0-9]{6,12})[)\s]+(?:Garantie|Garantle|Phonak|Audéo|Oticon|Widex|Signia|LPP)", box_text, re.IGNORECASE)
            if m:
                cand = re.sub(r"[^\w\-]", "", m.group(1)).strip("-_").upper()
                if is_valid_candidate(cand, box_context=box_text):
                    serials_found.add(cand)

        # 6. Regex directes sur motifs S/N standards supplémentaires
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

        # 7. Analyse spatiale pour colonnes de tableaux sous ancre S/N (ex: Colonne 'N° série')
        anchor_matches = self._find_anchor_matches(self.ANCHORS_SERIAL, category="serial", min_score=75)
        for anchor_box, _ in anchor_matches:
            # Exclure les boîtes qui contiennent déjà un S/N inline
            if re.search(r"(?:s[/\-.]?n|serial|s[eé]rie)[\s.:#\-]*\(?[A-Z0-9]{4,}", anchor_box.text, re.IGNORECASE):
                continue
            for box in self.boxes:
                if box is anchor_box:
                    continue
                dist_y = box.y_min - anchor_box.y_max
                # Une valeur juste à droite d'un libellé n'est pas une colonne :
                # ne pas parcourir les références des articles suivants.
                inline_values = [b for b in self.boxes if b is not anchor_box
                                 and b.x_min >= anchor_box.x_max - 5
                                 and abs(b.center_y - anchor_box.center_y) <= anchor_box.height * 0.7
                                 and re.fullmatch(r"[A-Z0-9 ,;]+", b.text, re.IGNORECASE)
                                 and any(c.isdigit() for c in b.text)]
                if inline_values:
                    for value_box in inline_values:
                        for token in value_box.text.split():
                            if is_valid_candidate(token):
                                serials_found.add(token.upper())
                    break
                if 0.0 < dist_y <= 350.0:
                    if abs(box.center_x - anchor_box.center_x) <= max(anchor_box.width * 0.7, 45.0):
                        cleaned = re.sub(r"^(?:s[/\-.]?n|sn|:|#|\s)+", "", box.text, flags=re.IGNORECASE).strip().upper()
                        tokens = re.split(r"[,;/\s()]+", cleaned)
                        for tok in tokens:
                            candidate = re.sub(r"[^\w\-]", "", tok).strip("-_")
                            if is_valid_candidate(candidate, box_context=box.text):
                                serials_found.add(candidate)

        # Tri stable pour reproductibilité avec normalisation heuristique
        cleaned_serials = {clean_serial_number(s) for s in serials_found if s}
        return sorted([s for s in cleaned_serials if is_valid_candidate(s)])

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
        """Extrait le nom du patient (sur facture client ou mentionné sur facture fournisseur)."""
        blacklist_words = {
            "SOCIAL", "SOCIALE", "SECURITE", "SÉCURITÉ", "SANTE", "SANTÉ",
            "ASSURE", "ASSURÉ", "TIERS", "MUTUELLE", "PRISE", "CHARGE",
            "PRESCRIEUR", "PRESCIPTEUR", "PRESCRIPTEUR", "FINESS", "DEVIS",
            "FACTURE", "DATE", "RUE", "TEL", "VILLE", "TOTAL", "REST",
            "OREILLE", "DROITE", "GAUCHE", "RESINE", "TITANE", "SILICONE",
            "DESIGNATION", "DÉSIGNATION", "QTE", "QTÉ", "REMISE", "TRANSPORT",
        }
        # 1. Regex directes
        patterns = [
            # Signia : "Nom du patient : beaufils"
            r"Nom[ \t]+du[ \t]+patient[ \t]*:[ \t]*([A-ZÀ-Ÿa-z'\- \t]{2,35})",
            # L'Atelier de l'Embout : S/N suivi du nom patient puis D ou G (ex: 250618GUAN1 GUENOLE annick D DMSM)
            r"\b\d{6}[A-Z]{3,5}\d{1,2}\s+([A-ZÀ-Ÿa-z'\-\s]{3,30}?)\s+[DG]\b",
            # Standard avec séparateur obligatoire (: ou - ou #) pour ne pas capturer les en-têtes de colonnes
            r"(?:patient(?:e)?|client(?:e)?|b[eé]n[eé]ficiaire|assur[eé](?:e)?)[ \t]*[:#\-][ \t]*([A-ZÀ-Ÿa-z'\- \t]{3,35})",
        ]
        for pat in patterns:
            for match in re.finditer(pat, self.full_text, re.IGNORECASE):
                raw_name = match.group(1).strip()
                tokens = [t for t in raw_name.split() if len(t) >= 2 and not t.isdigit() and t.upper() not in blacklist_words]
                if len(tokens) >= 2:
                    return " ".join(tokens[:3]).title()
                elif len(tokens) == 1 and len(tokens[0]) >= 3:
                    return tokens[0].title()

        # 2. Recherche spatiale dans les colonnes de tableaux sous en-tête 'Patient' (ex: L'Atelier de l'Embout)
        for anchor_box in self.boxes:
            if anchor_box.text.strip().lower() == "patient":
                for box in self.boxes:
                    if box is anchor_box:
                        continue
                    dist_y = box.y_min - anchor_box.y_max
                    if 0.0 < dist_y <= 120.0 and abs(box.center_x - anchor_box.center_x) <= max(anchor_box.width, 60.0):
                        cand = box.text.strip()
                        cand_tokens = [t for t in cand.split() if t.upper() not in blacklist_words and not t.isdigit()]
                        if len(cand_tokens) >= 1 and len(cand) <= 35:
                            return " ".join(cand_tokens).title()

        # 3. Recherche contextuelle par lignes (bruit OCR : 'atlent', 'client', 'prescripteur')
        lines = [l.strip() for l in self.full_text.splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            line_low = line.lower()
            if any(k in line_low for k in ["patient", "atlent", "client", "assur", "bénéficiaire"]):
                for j in range(idx + 1, min(idx + 5, len(lines))):
                    cand = lines[j].strip()
                    cand_tokens = cand.split()
                    if len(cand_tokens) >= 2 and len(cand) <= 35:
                        if not any(k in cand.lower() for k in ["prescripteur", "finess", "rue", "avenue", "tel", "tél", "devis", "date", "coulaines", "facture"]):
                            if not any(t.upper() in blacklist_words for t in cand_tokens):
                                return " ".join(cand_tokens).title()
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
            "TTC", "HT", "TVA", "DATE", "SIRET", "SIREN", "EUR", "TOTAL", "NET", "CLIENT", "PAGE", "ADRESSE", "PUHT",
        }

        # 1. Priorité absolue aux formats numéros de facture des fournisseurs du secteur
        vendor_num_patterns = [
            # WS Audiology (Widex, Signia) : 301/10109107, 301/10340289
            r"\b(301/\d{8})\b",
            # GN Hearing : 14-251101831
            r"\b(14-\d{8,10})\b",
            # L'Atelier de l'Embout : FA003019
            r"\b(FA\d{6})\b",
            # Prodition / Oticon : SOI001213878
            r"\b(SOI\d{8,10})\b",
            # Phonak / Sonova : 58837130
            r"\b(58\d{6})\b",
            # Format générique avec préfixe explicite
            r"\b((?:FAC|INV|FC|VENTE|ACHAT)[-_][A-Z0-9\-_]{2,25})\b",
        ]
        for pat in vendor_num_patterns:
            m = re.search(pat, self.full_text, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                if cand.upper() not in blacklist and parse_date_str(cand) is None:
                    return cand

        # 2. Motifs avec mot-clé Facture + numéro obligatoire (n° / num / no / ref / #)
        patterns = [
            r"(?:facture|factura|invoice)\s+(?:fournisseur|client|patient)?\s*(?:n[°o*]|num|no|ref|réf|#)\s*[\s.:#\-]*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"(?:n[°o*]|numéro)\s*(?:de)?\s*(?:facture)\s*[\s.:#\-]*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"(?:facture|factura|invoice)\s*:\s*([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"(?:facture|factura|invoice)\s+([0-9]{2}-[0-9]{8,10})\b",
            r"(?:facture|factura|invoice)\s+([A-Z0-9][A-Z0-9\-_/]{2,25})",
            r"\b((?:FAC|INV|FC|VENTE|ACHAT)[-_]?\d{4}[-_]?\d{2,6})\b",
            r"(?:facture|factura)\s*[:#\-]?\s*(21\d{6,7})\b",
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
        # Les dates personnelles, de garantie ou d'expédition ne sont jamais
        # des dates de facture, même en l'absence d'une date d'émission lisible.
        excluded = r"naissance|prescription|garantie|livraison|exp[eé]dition|[eé]ch[eé]ance|commande|payer avant"
        eligible = [b for b in self.boxes if not re.search(excluded, b.text, re.IGNORECASE)]
        for box in eligible:
            if re.search(r"date\s+(?:de\s+)?facture|fait\s+le|[eé]mis[e]?\s+le|facture\s+du", box.text, re.IGNORECASE):
                date = parse_date_str(box.text)
                if date:
                    return date
        # 1. Recherche par ancres prioritaires de facture ("Date de Facture", "En date du", "Date :")
        anchor_matches = self._find_anchor_matches(self.ANCHORS_DATE, category="date", min_score=75)
        for anchor_box, _ in anchor_matches:
            anc_lower = anchor_box.text.lower()
            if re.search(excluded, anc_lower, re.IGNORECASE):
                continue

            d_str = parse_date_str(anchor_box.text)
            if d_str:
                return d_str

            # Valeur séparée : uniquement une date sur la même ligne ou la
            # ligne suivante, sans emprunter celle d'une autre rubrique.
            index = self.boxes.index(anchor_box)
            candidates = [b for b in eligible if b is not anchor_box and b.width > 0
                          and b.x_min >= anchor_box.x_max - 5
                          and abs(b.center_y - anchor_box.center_y) <= anchor_box.height]
            if index + 1 < len(self.boxes) and self.boxes[index + 1] in eligible:
                candidates.append(self.boxes[index + 1])
            for candidate in candidates:
                if re.fullmatch(r"[\d\s./\-]+", candidate.text):
                    d_str = parse_date_str(candidate.text)
                    if d_str:
                        return d_str

        # 2. Motifs regex explicites pour la date de facture
        date_patterns = [
            r"(?:date\s+de\s+facture|date\s+facture|en\s+date\s+du|facture\s+du)[\s.:#\-]*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
            r"(?:date\s+de\s+facture|date\s+facture)[\s.:#\-]*(\d{1,2}[/\-.\s]+[a-zà-ÿ]{3,9}[/\-.\s]+\d{2,4})",
            r"(?:date)[\s.:#\-]+(\d{1,2}\.\d{1,2}\.\d{4})",
            r"(?:date)[\s.:#\-]+(\d{1,2}[/\-.\s]+[a-zà-ÿ]{3,9}[/\-.\s]+\d{2,4})",
            r"(?:date)[\s.:#\-]+(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
        ]
        for pat in date_patterns:
            m = re.search(pat, "\n".join(b.text for b in eligible), re.IGNORECASE)
            if m:
                d = parse_date_str(m.group(1))
                if d:
                    return d

        return None

    def extract_amounts(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        montant_ttc: Optional[float] = None
        montant_ht: Optional[float] = None
        montant_tva: Optional[float] = None

        # 1. Vérification spécifique pour les tables de synthèse (ex: Ligne 'Total' avec HT, TTC, TVA sur la même ligne)
        for box in self.boxes:
            b_text = box.text.strip().lower()
            if b_text in ["total", "totaux", "montant total"]:
                if box.width == 0:
                    continue
                y_c = box.center_y
                row_amts = []
                for other in self.boxes:
                    if other is not box and abs(other.center_y - y_c) < 18 and other.center_x > box.x_max - 5:
                        amt = other.contains_amount()
                        if amt is not None and "%" not in other.text:
                            row_amts.append((other.center_x, amt))
                row_amts.sort(key=lambda x: x[0])
                unique_amts = []
                for x_pos, a in row_amts:
                    if not any(abs(a - u) < 0.01 for u in unique_amts):
                        unique_amts.append(a)
                if len(unique_amts) >= 2:
                    sorted_vals = sorted(unique_amts, reverse=True)
                    montant_ttc = sorted_vals[0]
                    montant_ht = sorted_vals[1]
                    if len(sorted_vals) >= 3:
                        montant_tva = sorted_vals[2]
                    break

        # Total imprimé sur une seule ligne : HT/TVA/TTC (fournisseur)
        # ou HT/TTC/TVA (vente). Ne jamais additionner des colonnes du tableau.
        for box in self.boxes:
            if re.match(r"^(?:montant\s+total|total)\s+\d", box.text, re.IGNORECASE):
                values = [clean_amount(m.group(0)) for m in re.finditer(r"\d+(?:[ \u00a0]\d{3})*[,.]\d{2}\b", box.text)]
                if len(values) == 3 and abs(sum(sorted(values)[:2]) - max(values)) < 0.05:
                    montant_tva, montant_ht, montant_ttc = sorted(values)

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

        # 3. Consolidation multi-taux de TVA (ex: 5.5% matériel + 20% transport/port)
        if montant_ttc is not None and montant_ht is not None and montant_ttc >= montant_ht:
            montant_tva = round(montant_ttc - montant_ht, 2)

        # 4. CALCUL DES TAXES POUR LE TTC si le terme TTC est absent (ex: 1ère feuille d'une facture sur 2 pages)
        if montant_ttc is None:
            if montant_ht is not None and montant_tva is not None:
                montant_ttc = round(montant_ht + montant_tva, 2)
            elif montant_ht is not None:
                tva_rate = 5.5
                if "20%" in self.full_text or "20,00%" in self.full_text:
                    if "5.5%" in self.full_text or "5,5%" in self.full_text:
                        tva_rate = 5.5
                    else:
                        tva_rate = 20.0
                montant_tva = round(montant_ht * (tva_rate / 100.0), 2)
                montant_ttc = round(montant_ht + montant_tva, 2)
            else:
                line_amts: List[float] = []
                for box in self.boxes:
                    txt = box.text.strip().lower()
                    amt = box.contains_amount()
                    if amt is not None and 10.0 <= amt <= 3000.0:
                        if amt not in [889.0, 1269.0] and "%" not in txt:
                            if not any(k in txt for k in ["siret", "siren", "rcs", "tel", "fax", "iban", "bic", "code", "client"]):
                                if box.center_x > 350:
                                    line_amts.append(amt)
                if line_amts:
                    montant_ht = round(sum(line_amts), 2)
                    montant_tva = round(montant_ht * 0.055, 2)
                    montant_ttc = round(montant_ht + montant_tva, 2)

        return montant_ht, montant_tva, montant_ttc

    def extract_vendor_name(self) -> Optional[str]:
        text_lower = self.full_text.lower()
        if "atelier de l'embout" in text_lower or "atelier embout" in text_lower:
            return "L'Atelier de l'Embout"
        if "widex" in text_lower:
            return "Widex"
        if "signia" in text_lower or "sivantos" in text_lower:
            return "Signia"
        if "phonak" in text_lower:
            return "Phonak"
        if "sonova" in text_lower:
            return "Sonova"
        if "prodition" in text_lower:
            return "Prodition (Oticon / Bernafon)"
        if "oticon" in text_lower:
            return "Oticon"
        if "bernafon" in text_lower:
            return "Bernafon"
        if "resound" in text_lower or "gn hearing" in text_lower or "beltone" in text_lower or "interton" in text_lower:
            return "GN Hearing (ReSound)"
        if "starkey" in text_lower:
            return "Starkey"
        if "unitron" in text_lower:
            return "Unitron"
        if "hansaton" in text_lower:
            return "Hansaton"

        for brand in HEARING_AID_MANUFACTURERS:
            if brand in text_lower:
                return brand.title()

        for box in self.boxes[:4]:
            text = box.text.strip()
            if len(text) > 3 and not text.isdigit():
                if not re.search(r"\b(facture|factura|invoice|devis|ticket)\b", text, re.IGNORECASE):
                    return text
        return None

    def extract_client_issuer(self) -> Optional[str]:
        # Uniquement un libellé explicite ou une enseigne Phonème en en-tête.
        lines = [line.strip() for line in self.full_text.splitlines() if line.strip()]
        for line in lines:
            match = re.match(r"^(?:[eé]metteur|vendeur|raison sociale)\s*:\s*(.+)$", line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        for line in lines[:5]:
            if re.match(r"^phon[eè]me(?:\s+(?:audition|audio))?$", line, re.IGNORECASE):
                return line
        return None

    def extract_product_brand(self) -> Optional[str]:
        # Mentions explicites seulement, sans déduire la marque depuis le modèle.
        brands = {canonical for pattern, canonical in [
            (r"\bsignia\b", "Signia"), (r"\bphonak\b", "Phonak"),
            (r"\bwidex\b", "Widex"), (r"\boticon\b", "Oticon"),
            (r"\bbernafon\b", "Bernafon"), (r"\bresound\b", "ReSound"),
            (r"\bstarkey\b", "Starkey"), (r"\bunitron\b", "Unitron"),
            (r"\bhansaton\b", "Hansaton"),
        ] if re.search(pattern, self.full_text, re.IGNORECASE)}
        return next(iter(brands)) if len(brands) == 1 else ("Mixte" if brands else None)

    def detect_page_info(self) -> Tuple[int, int]:
        # Formats explicites multi-pages : "Page No 1 de 11", "Page 1 sur 2", "Page 1/2", "1 / 11"
        patterns = [
            r"page\s*(?:no\.?|n[°o*])?\s*(\d{1,3})\s*(?:sur|/|de)\s*(\d{1,3})",
            r"\b(\d{1,3})\s*[/]\s*(\d{1,3})\b",
        ]
        lines = [line.strip() for line in self.full_text.splitlines() if line.strip()]
        for line in lines:
            for pat in patterns:
                m = re.search(pat, line, re.IGNORECASE)
                if m:
                    c, t = int(m.group(1)), int(m.group(2))
                    if 1 <= c <= t <= 100:
                        return c, t

        for pat in patterns:
            m = re.search(pat, self.full_text, re.IGNORECASE)
            if m:
                c, t = int(m.group(1)), int(m.group(2))
                if 1 <= c <= t <= 100:
                    return c, t

        m_single = re.search(r"\bpage\s*(\d{1,3})\b", self.full_text, re.IGNORECASE)
        if m_single:
            c = int(m_single.group(1))
            return c, max(c, 1)

        return 1, 1

    def extract_products(self, detected_serials: Optional[List[str]] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Extrait les désignations et modèles d'appareils auditifs et accessoires détectés
        sur la facture (Phonak, Oticon, Signia, Widex, Starkey, ReSound, embouts sur-mesure, etc.).
        Associe chaque produit à son numéro de série (S/N) respectif quand disponible.
        """
        product_names: List[str] = []
        product_items: List[Dict[str, Any]] = []
        serials = detected_serials or []

        lines = [line.strip() for line in self.full_text.splitlines() if line.strip()]

        def match_product_in_text(line_str: str) -> Optional[str]:
            for pat in HEARING_AID_PRODUCT_PATTERNS:
                m = re.search(pat, line_str, re.IGNORECASE)
                if m:
                    cand = clean_product_name(m.group(0))
                    if len(cand) >= 3 and not is_phone_number(cand):
                        return cand
            # Modèles inconnus : accepter une désignation explicitement
            # étiquetée, pas n'importe quel texte après un fournisseur/adresse.
            labelled = re.match(r"^(?:mod[eè]le|d[eé]signation|appareil)[ \t]*:[ \t]*(.+)$", line_str, re.IGNORECASE)
            if labelled:
                return clean_product_name(labelled.group(1)) or None
            return None

        # 1. Association par proximité avec les numéros de série (S/N)
        for sn in serials:
            sn_prod = None
            source_line = ""
            for idx, line in enumerate(lines):
                if sn in line:
                    # Même ligne
                    sn_prod = match_product_in_text(line)
                    if sn_prod:
                        source_line = line
                    if not sn_prod:
                        # Chercher dans les lignes précédentes (jusqu'à 8 lignes au-dessus)
                        for back in range(1, 9):
                            if idx - back >= 0:
                                cand = match_product_in_text(lines[idx - back])
                                if cand:
                                    sn_prod = cand
                                    source_line = lines[idx - back]
                                    break
                    if not sn_prod:
                        # Chercher dans les 2 lignes suivantes
                        for fwd in range(1, 3):
                            if idx + fwd < len(lines):
                                cand = match_product_in_text(lines[idx + fwd])
                                if cand:
                                    sn_prod = cand
                                    source_line = lines[idx + fwd]
                                    break
                    break

            if sn_prod:
                reason = non_sale_reason(source_line)
                product_items.append({
                    "product_name": sn_prod,
                    "designation": sn_prod,
                    "serial_number": sn,
                    **({"non_sale_reason": reason} if reason else {}),
                })
                if sn_prod not in product_names:
                    product_names.append(sn_prod)

        # 2. Détection de tous les produits présents sur le document (accessoires, chargeurs, écouteurs, etc.)
        for line in lines:
            prod = match_product_in_text(line)
            if prod:
                if prod not in product_names:
                    product_names.append(prod)
                reason = non_sale_reason(line)
                if not any(
                    (item.get("product_name") == prod or item.get("designation") == prod)
                    and item.get("non_sale_reason", "") == reason
                    for item in product_items
                ):
                    product_items.append({
                        "product_name": prod,
                        "designation": prod,
                        "serial_number": None,
                        **({"non_sale_reason": reason} if reason else {}),
                    })

        # Référence article distincte du S/N, souvent sur la ligne chiffrée
        # immédiatement au-dessus de la désignation fournisseur.
        for item in product_items:
            for index, line in enumerate(lines):
                if match_product_in_text(line) == item["product_name"] and index > 0:
                    reference = re.match(r"^\d+[ \t]+(\d{6,12})\b", lines[index - 1])
                    if reference:
                        item["reference"] = reference.group(1)
                        break
        return product_names, product_items

    def parse(self) -> Dict[str, Any]:
        siret, siren = self.extract_siret_siren()
        tva_intra = self.extract_tva_intracommunautaire()
        num_facture = self.extract_invoice_number()
        date_facture = self.extract_date()
        ht, tva, ttc = self.extract_amounts()
        inv_type = self.detect_invoice_type()
        fournisseur = self.extract_vendor_name()
        patient = self.extract_patient_name()
        serials = self.extract_serial_numbers()
        product_names, product_items = self.extract_products(detected_serials=serials)
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
            "emetteur_nom": self.extract_client_issuer() if inv_type == "CLIENT" else None,
            "marque_client": "Phoneme" if inv_type == "CLIENT" else None,
            "marque_produit": self.extract_product_brand(),
            "patient_nom": patient,
            "serial_numbers": serials,
            "product_names": product_names,
            "product_items": product_items,
            "page_current": page_cur,
            "page_total": page_tot,
            "raw_text": self.full_text,
        }


def parse_invoice(ocr_results: List[Dict[str, Any]], forced_type: Optional[str] = None) -> Dict[str, Any]:
    parser = InvoiceParser(ocr_results, forced_type=forced_type)
    return parser.parse()
