"""
Module de validation financière, légale et d'intégrité des factures.
Exécute 4 contrôles indépendants :
1. Légal : Algorithme de Luhn (SIRET/SIREN) et clé TVA intracommunautaire française.
2. Arithmétique : Équation fiscale |HT + TVA - TTC| <= 0.02.
3. Chronologique : Date d'émission <= date du jour.
4. Unicité : Hash SHA-256 composite anti-doublon.
"""

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import hashlib
import logging
import re

logger = logging.getLogger("FactureChecker.Validator")


def verify_luhn(number_str: str) -> bool:
    """
    Vérifie la validité d'une chaîne numérique selon l'algorithme de Luhn (base 10).
    Utilisé pour la validation officielle des numéros SIREN (9 chiffres) et SIRET (14 chiffres).

    Args:
        number_str (str): Chaîne contenant uniquement des chiffres.

    Returns:
        bool: True si la somme de Luhn est un multiple de 10, False sinon.
    """
    clean_digits = re.sub(r"\D", "", number_str)
    if not clean_digits:
        return False

    total = 0
    # Parcours de droite à gauche :
    # rang 1 (dernier chiffre) * 1, rang 2 * 2, rang 3 * 1, etc.
    for i, char in enumerate(reversed(clean_digits), start=1):
        d = int(char)
        if i % 2 == 0:
            doubled = d * 2
            total += (doubled - 9) if doubled > 9 else doubled
        else:
            total += d

    return total % 10 == 0


def compute_french_vat_key(siren: str) -> Optional[int]:
    """
    Calcule la clé du numéro de TVA intracommunautaire français à partir du SIREN.
    Formule légale : [12 + 3 * (SIREN % 97)] % 97

    Args:
        siren (str): Numéro SIREN (9 chiffres).

    Returns:
        Optional[int]: Clé sur 2 chiffres (0 à 96), ou None si le SIREN est invalide.
    """
    clean_siren = re.sub(r"\D", "", siren)
    if len(clean_siren) != 9:
        return None
    try:
        siren_int = int(clean_siren)
        return (12 + 3 * (siren_int % 97)) % 97
    except ValueError:
        return None


def generate_invoice_hash(
    siret: Optional[str],
    date_str: Optional[str],
    num_facture: Optional[str],
    montant_ttc: Optional[float],
    filename: Optional[str] = None,
) -> str:
    """
    Génère un hash SHA-256 composite unique identifiant la facture :
    fournisseur_siret + date + num_facture + montant_ttc

    Si les identifiants clés sont manquants, le nom de fichier est inclus
    afin d'éviter les collisions entre documents non reconnus.

    Returns:
        str: Empreinte SHA-256 hexadécimale (64 caractères).
    """
    norm_siret = (siret or "").strip().upper()
    norm_date = (date_str or "").strip()
    norm_num = (num_facture or "").strip().upper()
    norm_ttc = f"{montant_ttc:.2f}" if montant_ttc is not None else "0.00"

    # Si aucun identifiant n'est extrait, signature unique par fichier
    if not norm_siret and not norm_num and filename:
        raw_signature = f"{filename}_{norm_date}_{norm_ttc}"
    else:
        raw_signature = f"{norm_siret}_{norm_date}_{norm_num}_{norm_ttc}"

    return hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()


class InvoiceValidator:
    """
    Validateur d'intégrité financière et légale pour factures fournisseurs.
    """

    STATUS_VALIDE = "VALIDE"
    STATUS_ERREUR_CALCUL = "ERREUR_CALCUL"
    STATUS_SIRET_INVALIDE = "SIRET_INVALIDE"
    STATUS_DOUBLON = "DOUBLON"
    STATUS_A_VERIFIER = "A_VERIFIER"

    def __init__(
        self,
        db_is_duplicate_fn: Optional[Callable[[str], bool]] = None,
        max_arithmetic_tolerance: float = 0.02,
    ) -> None:
        self.is_duplicate_fn = db_is_duplicate_fn
        self.max_tolerance = max_arithmetic_tolerance

    def validate_legal(
        self,
        siret: Optional[str],
        siren: Optional[str],
        tva_intra: Optional[str],
    ) -> Tuple[bool, List[str]]:
        """1. Contrôle Légal : Algorithme de Luhn et TVA intracommunautaire."""
        errors: List[str] = []

        if not siret and not siren:
            errors.append("Numéro SIRET et SIREN introuvables sur le document.")
        else:
            if siret:
                clean_siret = re.sub(r"\D", "", siret)
                if len(clean_siret) != 14:
                    errors.append(f"Format SIRET invalide (longueur {len(clean_siret)} != 14).")
                elif not verify_luhn(clean_siret):
                    errors.append(f"Échec de l'algorithme de Luhn sur le SIRET ({siret}).")
            if siren:
                clean_siren = re.sub(r"\D", "", siren)
                if len(clean_siren) != 9:
                    errors.append(f"Format SIREN invalide (longueur {len(clean_siren)} != 9).")
                elif not verify_luhn(clean_siren):
                    errors.append(f"Échec de l'algorithme de Luhn sur le SIREN ({siren}).")

        if tva_intra:
            clean_tva = re.sub(r"[\s.-]", "", tva_intra).upper()
            if clean_tva.startswith("FR") and len(clean_tva) == 13:
                key_str = clean_tva[2:4]
                tva_siren = clean_tva[4:]
                if key_str.isdigit():
                    expected_key = compute_french_vat_key(tva_siren)
                    actual_key = int(key_str)
                    if expected_key is not None and actual_key != expected_key:
                        errors.append(
                            f"Clé TVA intra invalide : clé lue '{key_str}' != clé calculée '{expected_key:02d}'."
                        )
                    if siren and tva_siren != re.sub(r"\D", "", siren):
                        errors.append(
                            f"Incohérence : le SIREN de la TVA intra ({tva_siren}) ne correspond pas au SIREN ({siren})."
                        )
            else:
                errors.append(f"Format de TVA intracommunautaire non conforme : {tva_intra}")

        return len(errors) == 0, errors

    def validate_arithmetic(
        self,
        ht: Optional[float],
        tva: Optional[float],
        ttc: Optional[float],
    ) -> Tuple[bool, List[str]]:
        """2. Contrôle Arithmétique : |HT + TVA - TTC| <= 0.02."""
        errors: List[str] = []

        if ht is None or ttc is None:
            errors.append(
                f"Montants incomplets pour le contrôle arithmétique (HT={ht}, TVA={tva}, TTC={ttc})."
            )
            return False, errors

        tva_calc = tva if tva is not None else 0.0
        delta = abs((ht + tva_calc) - ttc)

        if delta > self.max_tolerance:
            errors.append(
                f"Écart arithmétique détecté : HT ({ht:.2f}) + TVA ({tva_calc:.2f}) = "
                f"{ht + tva_calc:.2f} != TTC ({ttc:.2f}) (écart : {delta:.2f} € > {self.max_tolerance:.2f} €)."
            )
            return False, errors

        return True, errors

    def validate_chronological(self, date_str: Optional[str]) -> Tuple[bool, List[str]]:
        """3. Contrôle Chronologique : Date <= date courante."""
        errors: List[str] = []
        if not date_str:
            errors.append("Date de facture introuvable.")
            return False, errors

        try:
            if "-" in date_str:
                invoice_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            elif "/" in date_str:
                invoice_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            else:
                invoice_date = datetime.fromisoformat(date_str).date()
        except ValueError:
            errors.append(f"Format de date non reconnu : '{date_str}'.")
            return False, errors

        today = date.today()
        if invoice_date > today:
            errors.append(
                f"Anomalie chronologique : date d'émission ({invoice_date}) postérieure à la date du jour ({today})."
            )
            return False, errors

        return True, errors

    def validate_uniqueness(
        self,
        unique_hash: str,
        has_primary_identifiers: bool = True,
    ) -> Tuple[bool, List[str]]:
        """4. Contrôle d'Unicité anti-doublon."""
        errors: List[str] = []
        if has_primary_identifiers and self.is_duplicate_fn and self.is_duplicate_fn(unique_hash):
            errors.append(f"Facture déjà existante en base (doublon détecté, hash={unique_hash[:12]}...).")
            return False, errors
        return True, errors

    def validate(self, parsed_data: Dict[str, Any]) -> Tuple[str, List[str], str]:
        """
        Exécute les 4 contrôles indépendants et détermine le statut d'intégrité global.
        """
        siret = parsed_data.get("siret")
        siren = parsed_data.get("siren")
        tva_intra = parsed_data.get("tva_intracommunautaire")
        date_facture = parsed_data.get("date_facture")
        num_facture = parsed_data.get("numero_facture")
        ht = parsed_data.get("montant_ht")
        tva = parsed_data.get("montant_tva")
        ttc = parsed_data.get("montant_ttc")
        filename = parsed_data.get("filename")

        has_ident = bool((siret or siren) and (num_facture or ttc is not None))

        # 1. Calcul du hash composite SHA-256
        unique_hash = generate_invoice_hash(
            siret or siren, date_facture, num_facture, ttc, filename=filename
        )

        # 2. Exécution des 4 contrôles
        legal_valid, legal_errors = self.validate_legal(siret, siren, tva_intra)
        arith_valid, arith_errors = self.validate_arithmetic(ht, tva, ttc)
        chrono_valid, chrono_errors = self.validate_chronological(date_facture)
        unique_valid, unique_errors = self.validate_uniqueness(
            unique_hash, has_primary_identifiers=has_ident
        )

        all_errors = legal_errors + arith_errors + chrono_errors + unique_errors

        # 3. Détermination du statut (le SIRET n'est plus bloquant)
        if not unique_valid:
            status = self.STATUS_DOUBLON
        elif not arith_valid and (ht is not None and ttc is not None):
            status = self.STATUS_ERREUR_CALCUL
        elif not chrono_valid or not arith_valid or (not num_facture and ttc is None):
            status = self.STATUS_A_VERIFIER
        else:
            status = self.STATUS_VALIDE

        return status, all_errors, unique_hash
