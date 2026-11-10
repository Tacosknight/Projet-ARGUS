#!/usr/bin/env python3
"""
Point d'entrée principal pour Facture-Checker.
Automatise le scan par lot de photos de factures, le pré-traitement de vision,
l'extraction OCR PaddleOCR, le parsing géométrique des montants et numéros de série (S/N),
l'audit d'intégrité financière/légale, le rapprochement Dépenses <-> Refacturations,
l'enregistrement en base SQLite et l'export dynamique vers Excel.
"""

import argparse
from datetime import datetime
import logging
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional

# Priorisation des chemins
current_dir = Path(__file__).resolve().parent
if (current_dir / "core").exists():
    sys.path.insert(0, str(current_dir))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("FactureChecker.Main")

from core.preprocessor import preprocess_image
from core.ocr_engine import OCREngine
from core.parser import parse_invoice
from core.validator import InvoiceValidator
from core.multipage import are_pages_of_same_invoice, consolidate_pages
from core.reconciliation import reconcile_invoices
from storage.database import InvoiceDatabase
from storage.export_excel import export_to_excel
from core.app_paths import DATABASE_PATH, EXCEL_PATH, INPUT_DIR, ensure_app_directories
from core.document_loader import DOCUMENT_EXTENSIONS, iter_document_pages


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"
ANSI_GRAY = "\033[90m"
ANSI_BLUE = "\033[94m"


def colorize_status(status: str) -> str:
    if status == "VALIDE":
        return f"{ANSI_GREEN}{ANSI_BOLD}✔ VALIDE{ANSI_RESET}"
    elif status == "ERREUR_CALCUL":
        return f"{ANSI_RED}{ANSI_BOLD}✘ ERREUR_CALCUL{ANSI_RESET}"
    elif status == "SIRET_INVALIDE":
        return f"{ANSI_RED}{ANSI_BOLD}✘ SIRET_INVALIDE{ANSI_RESET}"
    elif status == "DOUBLON":
        return f"{ANSI_YELLOW}{ANSI_BOLD}⚠ DOUBLON{ANSI_RESET}"
    else:
        return f"{ANSI_YELLOW}{ANSI_BOLD}? A_VERIFIER{ANSI_RESET}"


def process_single_image(
    image_path: Path,
    ocr_engine: OCREngine,
    validator: InvoiceValidator,
    db: InvoiceDatabase,
    forced_type: Optional[str] = None,
    save_debug_dir: Optional[Path] = None,
    page_current: int = 1,
    page_total: int = 1,
    pdf_source_path: Optional[Path] = None,
) -> Dict[str, Any]:
    filename = image_path.name
    logger.info("Traitement du fichier : %s", filename)

    invoice_record: Dict[str, Any] = {
        "filename": filename,
        "invoice_type": forced_type or "FOURNISSEUR",
        "siret": None,
        "siren": None,
        "numero_facture": None,
        "date_facture": None,
        "montant_ht": None,
        "montant_tva": None,
        "montant_ttc": None,
        "tva_intracommunautaire": None,
        "fournisseur_nom": None,
        "patient_nom": None,
        "serial_numbers": [],
        "status": "A_VERIFIER",
        "error_details": [],
        "unique_hash": None,
        "created_at": datetime.now().isoformat(),
        "raw_text": "",
    }

    try:
        # Une page PDF n'utilise le texte natif que si le sélecteur l'accepte.
        ocr_results = None
        if pdf_source_path is not None:
            try:
                from core.pdf_native import native_pdf_page
                ocr_results, _reason = native_pdf_page(pdf_source_path, page_current)
            except Exception:
                # Ne pas journaliser l'exception : elle peut contenir du texte sensible.
                logger.warning("Extraction native PDF impossible, repli sur l'OCR (page %s).", page_current)
            logger.info("Page PDF %s/%s : %s", page_current, page_total,
                        "texte natif" if ocr_results else "OCR")

        if not ocr_results:
            preprocessed = preprocess_image(image_path, target_height=1600, apply_threshold=True)

            if save_debug_dir:
                save_debug_dir.mkdir(parents=True, exist_ok=True)
                import cv2
                debug_out = save_debug_dir / f"preprocessed_{filename}"
                cv2.imwrite(str(debug_out), preprocessed)

            ocr_results = ocr_engine.extract_text_and_boxes(preprocessed)
            if not ocr_results:
                invoice_record["status"] = "A_VERIFIER"
                invoice_record["error_details"] = ["Aucun texte lisible détecté par l'OCR sur cette image."]
                db.save_invoice(invoice_record)
                return invoice_record

        # 3. Parsing (métadonnées, S/N et type de facture)
        parsed = parse_invoice(ocr_results, forced_type=forced_type)
        invoice_record.update({
            "invoice_type": parsed.get("invoice_type", "FOURNISSEUR"),
            "siret": parsed.get("siret"),
            "siren": parsed.get("siren"),
            "numero_facture": parsed.get("numero_facture"),
            "date_facture": parsed.get("date_facture"),
            "montant_ht": parsed.get("montant_ht"),
            "montant_tva": parsed.get("montant_tva"),
            "montant_ttc": parsed.get("montant_ttc"),
            "tva_intracommunautaire": parsed.get("tva_intracommunautaire"),
            "fournisseur_nom": parsed.get("fournisseur_nom"),
            "patient_nom": parsed.get("patient_nom"),
            "serial_numbers": parsed.get("serial_numbers", []),
            "raw_text": parsed.get("raw_text", ""),
            "page_current": page_current if page_total > 1 else parsed.get("page_current", 1),
            "page_total": page_total if page_total > 1 else parsed.get("page_total", 1),
        })

        # Assemblage multi-pages avec les factures existantes (ex: Page 1 + Page 2)
        existing_invoices = db.get_all_invoices()
        matching_partner = None
        for old_inv in existing_invoices:
            if are_pages_of_same_invoice(old_inv, invoice_record):
                matching_partner = old_inv
                break

        if matching_partner:
            logger.info(
                "Facture multi-pages détectée : fusion de '%s' avec '%s'",
                filename,
                matching_partner.get("filename"),
            )
            invoice_record = consolidate_pages([matching_partner, invoice_record])
            if matching_partner.get("id"):
                try:
                    db.delete_invoice(matching_partner["id"])
                except Exception:
                    pass

        # 4. Validation d'intégrité
        status, errors, unique_hash = validator.validate(invoice_record)
        invoice_record["status"] = status
        invoice_record["error_details"] = errors
        invoice_record["unique_hash"] = unique_hash

        # 5. Sauvegarde SQLite
        db.save_invoice(invoice_record)

    except Exception as exc:
        logger.exception("Erreur inattendue lors du traitement de '%s' : %s", filename, exc)
        invoice_record["status"] = "A_VERIFIER"
        invoice_record["error_details"] = [f"Erreur technique : {str(exc)}"]
        try:
            db.save_invoice(invoice_record)
        except Exception:
            pass

    return invoice_record


def run_batch_processing(
    input_dir: Path,
    db_path: Path,
    output_excel: Path,
    save_debug: bool = False,
) -> None:
    print(f"\n{ANSI_BOLD}{ANSI_CYAN}=== DÉMARRAGE DU TRAITEMENT DES FACTURES ==={ANSI_RESET}")
    print(f"Dossier source des images : {input_dir.resolve()}")
    print(f"Base de données SQLite    : {db_path.resolve()}")
    print(f"Rapport Excel dynamique   : {output_excel.resolve()}\n")

    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"{ANSI_YELLOW}Dossier '{input_dir}' créé. Déposez-y des images à traiter.{ANSI_RESET}")
        return

    # Recherche récursive ou directe des images
    image_files = sorted([
        f for f in input_dir.glob("**/*")
        if f.is_file() and f.suffix.lower() in DOCUMENT_EXTENSIONS and "debug" not in f.name.lower()
    ])

    if not image_files:
        print(f"{ANSI_YELLOW}Aucune image trouvée dans '{input_dir}'.{ANSI_RESET}")
        return

    print(f"{len(image_files)} fichier(s) détecté(s) pour audit & rapprochement.\n")

    db = InvoiceDatabase(str(db_path))
    validator = InvoiceValidator(db_is_duplicate_fn=db.is_hash_exists)

    print(f"{ANSI_GRAY}Initialisation du moteur PaddleOCR (Français)...{ANSI_RESET}")
    ocr_engine = OCREngine(lang="fr", show_log=False)


    debug_dir = (input_dir / "debug_preprocessed") if save_debug else None

    processed_count = 0
    status_summary = {
        "VALIDE": 0,
        "ERREUR_CALCUL": 0,
        "SIRET_INVALIDE": 0,
        "DOUBLON": 0,
        "A_VERIFIER": 0,
    }

    print("-" * 105)
    print(f"{'FICHIER':<24} | {'TYPE':<11} | {'N° FACTURE':<13} | {'TTC':<10} | {'S/N DÉTECTÉ(S)':<16} | {'STATUT':<18}")
    print("-" * 105)

    for img_path in image_files:
        # Si placé dans sous-dossier clients ou fournisseurs
        forced = None
        if "client" in str(img_path).lower():
            forced = "CLIENT"
        elif "fournisseur" in str(img_path).lower() or "fabricant" in str(img_path).lower():
            forced = "FOURNISSEUR"

        temporary_dir = None
        res = None
        try:
            pages_to_process = [(img_path, 1, 1)]
            if img_path.suffix.lower() == ".pdf":
                temporary_dir = tempfile.TemporaryDirectory(prefix="argus-pdf-")
                pages_to_process = []
                for page_number, page_total, page_image in iter_document_pages(img_path):
                    page_path = Path(temporary_dir.name) / f"{img_path.stem}_p{page_number}_sur_{page_total}.jpg"
                    import cv2
                    if not cv2.imwrite(str(page_path), page_image):
                        raise OSError("Impossible d'écrire l'image temporaire de la page PDF")
                    pages_to_process.append((page_path, page_number, page_total))

            for page_path, page_number, page_total in pages_to_process:
                res = process_single_image(
                    image_path=page_path,
                    ocr_engine=ocr_engine,
                    validator=validator,
                    db=db,
                    forced_type=forced,
                    save_debug_dir=debug_dir,
                    page_current=page_number,
                    page_total=page_total,
                    pdf_source_path=img_path if img_path.suffix.lower() == ".pdf" else None,
                )
        finally:
            if temporary_dir is not None:
                temporary_dir.cleanup()
        if res is None:
            continue
        processed_count += 1
        st = res["status"]
        status_summary[st] = status_summary.get(st, 0) + 1

        num_fac = res.get("numero_facture") or "N/A"
        ttc = f"{res.get('montant_ttc'):.2f} €" if res.get("montant_ttc") is not None else "N/A"
        inv_type = (res.get("invoice_type") or "FOURNISSEUR").upper()
        type_badge = f"{ANSI_BLUE}VENTE{ANSI_RESET}" if inv_type == "CLIENT" else f"{ANSI_GRAY}ACHAT{ANSI_RESET}"

        serials = res.get("serial_numbers") or []
        serials_str = ", ".join(serials) if serials else "Aucun"
        if len(serials_str) > 15:
            serials_str = serials_str[:13] + ".."

        st_colored = colorize_status(st)
        fname_short = img_path.name[:22]
        if res.get("is_multipage"):
            fname_short = f"🔗 [Multi] {img_path.name[:12]}"
        print(f"{fname_short:<24} | {type_badge:<20} | {num_fac:<13} | {ttc:<10} | {serials_str:<16} | {st_colored}")

    print("-" * 105)

    # Export Excel dynamique avec onglet de réconciliation
    print(f"\n{ANSI_GRAY}Génération du classeur Excel avec onglet de rapprochement S/N...{ANSI_RESET}")
    all_invoices = db.get_all_invoices()
    excel_path = export_to_excel(all_invoices, output_path=output_excel)

    # Réconciliation des S/N
    reconcil_res = reconcile_invoices(all_invoices)
    rec_kpi = reconcil_res["kpi"]
    rec_items = reconcil_res["items"]

    # Affichage du rapport de rapprochement
    if rec_items:
        print(f"\n{ANSI_BOLD}{ANSI_CYAN}=== RAPPROCHEMENT PAR N° DE SÉRIE (PROTHÈSES AUDITIVES) ==={ANSI_RESET}")
        print("-" * 105)
        print(f"{'N° SÉRIE (S/N)':<15} | {'ACHAT FABRICANT':<20} | {'COÛT TTC':<10} | {'VENTE PATIENT':<20} | {'PRIX TTC':<10} | {'STATUT'}")
        print("-" * 105)
        for item in rec_items:
            sn = item["serial_number"]
            st = item["status"]
            fourn_str = (item.get('fournisseur_nom') or '-')[:10]
            achat_info = f"{fourn_str} ({item.get('achat_num_facture') or '-'})"
            achat_prix = item.get('achat_prix_ttc')
            achat_ttc = f"{achat_prix:.2f} €" if (achat_prix is not None and achat_prix > 0) else "-"

            patient_str = (item.get('patient_nom') or '-')[:10]
            vente_info = f"{patient_str} ({item.get('vente_num_facture') or '-'})"
            vente_prix = item.get('vente_prix_ttc')
            vente_ttc = f"{vente_prix:.2f} €" if (vente_prix is not None and vente_prix > 0) else "-"


            if st == "RAPPROCHE":
                st_str = f"{ANSI_GREEN}{ANSI_BOLD}✔ RAPPROCHÉ{ANSI_RESET}"
            elif st == "NON_REFACTURE":
                st_str = f"{ANSI_RED}{ANSI_BOLD}✘ NON REFACTURÉ{ANSI_RESET}"
            else:
                st_str = f"{ANSI_YELLOW}{ANSI_BOLD}⚠ ACHAT MANQUANT{ANSI_RESET}"

            print(f"{sn:<15} | {achat_info:<20} | {achat_ttc:<10} | {vente_info:<20} | {vente_ttc:<10} | {st_str}")
        print("-" * 105)

    # Rapport final
    print(f"\n{ANSI_BOLD}{ANSI_CYAN}=== SYNTHÈSE GLOBALE ==={ANSI_RESET}")
    print(f"Factures traitées : {processed_count}")
    print(f"  • {ANSI_GREEN}Conformes (VALIDE)      : {status_summary['VALIDE']}{ANSI_RESET}")
    print(f"  • {ANSI_RED}Erreurs arithmétiques   : {status_summary['ERREUR_CALCUL']}{ANSI_RESET}")
    print(f"  • {ANSI_RED}SIRET/Luhn invalides    : {status_summary['SIRET_INVALIDE']}{ANSI_RESET}")
    print(f"  • {ANSI_YELLOW}Doublons bloqués        : {status_summary['DOUBLON']}{ANSI_RESET}")
    print(f"\nRapprochement Prothèses (S/N) :")
    print(f"  • Total appareils tracés        : {rec_kpi['total_serials_detected']}")
    print(f"  • {ANSI_GREEN}Appareils rapprochés          : {rec_kpi['rapproches_count']}{ANSI_RESET}")
    print(f"  • {ANSI_RED}Appareils NON REFACTURÉS      : {rec_kpi['non_refactures_count']} (Dépenses : {rec_kpi['volume_dépenses_orphelines']:.2f} €){ANSI_RESET}")
    print(f"  • Taux de couverture            : {rec_kpi['taux_couverture']} %")
    print(f"\nDonnées archivées dans SQLite : {db_path.resolve()}")
    print(f"Classeur Excel complet        : {Path(excel_path).resolve()}\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Facture-Checker : Audit automatisé et rapprochement S/N prothèses auditives."
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(INPUT_DIR),
        help="Dossier contenant les images ou PDF (défaut: dossier ARGUS de l'utilisateur).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DATABASE_PATH),
        help="Chemin de la base SQLite (défaut: dossier ARGUS de l'utilisateur).",
    )
    parser.add_argument(
        "--output-excel",
        type=str,
        default=str(EXCEL_PATH),
        help="Chemin du classeur Excel (défaut: dossier ARGUS de l'utilisateur).",
    )
    parser.add_argument(
        "--save-debug",
        action="store_true",
        help="Sauvegarder les images pré-traitées redressées pour inspection visuelle.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Lancer le serveur Web Mobile (accessible depuis votre smartphone via Wi-Fi).",
    )
    return parser.parse_args()


def main() -> None:
    ensure_app_directories()
    args = parse_arguments()
    if args.web:
        from server import main as run_web_server
        run_web_server()
        return

    run_batch_processing(
        input_dir=Path(args.input_dir),
        db_path=Path(args.db_path),
        output_excel=Path(args.output_excel),
        save_debug=args.save_debug,
    )


if __name__ == "__main__":
    main()
