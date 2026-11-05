"""
Application Web FastAPI Mobile-First pour Facture-Checker.
Permet de photographier une facture (Achat Fabricant ou Vente Patient)
avec la caméra du smartphone, d'extraire les numéros de série (S/N),
d'analyser l'intégrité légale et de suivre le rapprochement financier en temps réel.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
import re
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
import cv2
import numpy as np

# Imports internes Facture-Checker
import sys
current_dir = Path(__file__).resolve().parent.parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from core.preprocessor import preprocess_image
from core.ocr_engine import OCREngine
from core.parser import parse_invoice
from core.validator import InvoiceValidator
from core.reconciliation import reconcile_invoices
from core.comparator import compare_invoices
from core.multipage import consolidate_pages, are_pages_of_same_invoice
from storage.database import InvoiceDatabase
from storage.export_excel import export_to_excel

logger = logging.getLogger("FactureChecker.Web")

app = FastAPI(
    title="Facture-Checker Mobile",
    description="Scanner et auditeur de factures d'aides auditives avec rapprochement S/N.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Détection intelligente du chemin de la BDD et de l'export Excel (répertoire courant ou BASE_DIR)
CWD_DB = Path.cwd() / "invoices.db"
DB_PATH = CWD_DB if CWD_DB.exists() else (BASE_DIR / "invoices.db")

CWD_EXCEL = Path.cwd() / "factures_synthese.xlsx"
EXCEL_PATH = CWD_EXCEL if CWD_EXCEL.exists() else (BASE_DIR / "factures_synthese.xlsx")

INPUT_DIR = Path.cwd() / "input_photos" if (Path.cwd() / "input_photos").exists() else (BASE_DIR / "input_photos")
INPUT_DIR.mkdir(parents=True, exist_ok=True)

# Instances partagées
db = InvoiceDatabase(str(DB_PATH))
validator = InvoiceValidator(db_is_duplicate_fn=db.is_hash_exists)
ocr_engine = OCREngine(lang="fr")



@app.get("/", response_class=HTMLResponse)
async def serve_mobile_ui() -> HTMLResponse:
    index_file = Path(__file__).parent / "templates" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Facture-Checker Web UI</h1>")


def process_uploaded_invoice_files(
    uploaded_files: List[UploadFile],
    invoice_type: Optional[str] = None,
    prefix: str = "scan",
) -> Dict[str, Any]:
    """
    Traite un ensemble de fichiers/photos correspondant à une même facture :
    - Sauvegarde dans input_photos
    - Pré-traitement de vision (redressement 4 points, seuillage)
    - OCR déterministe PaddleOCR
    - Parsing des métadonnées et extraction des numéros de série (S/N)
    - Consolidation multi-pages
    - Validation d'intégrité et archivage en base SQLite
    """
    if not uploaded_files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni pour l'analyse.")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    parsed_pages: List[Dict[str, Any]] = []

    for idx, ufile in enumerate(uploaded_files, 1):
        if not ufile.filename:
            continue
        safe_filename = f"{prefix}_{timestamp_str}_p{idx}_{Path(ufile.filename).name}"
        saved_path = INPUT_DIR / safe_filename

        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(ufile.file, buffer)

        # Support des documents PDF (multi-pages inclus)
        if saved_path.suffix.lower() == ".pdf":
            try:
                import pypdfium2 as pdfium
                pdf_doc = pdfium.PdfDocument(str(saved_path))
                total_pdf_pages = len(pdf_doc)
                for page_idx in range(total_pdf_pages):
                    page = pdf_doc[page_idx]
                    pil_img = page.render(scale=2).to_pil()
                    bgr_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

                    pdf_page_filename = f"{prefix}_{timestamp_str}_f{idx}_p{page_idx + 1}.jpg"
                    pdf_page_path = INPUT_DIR / pdf_page_filename
                    cv2.imwrite(str(pdf_page_path), bgr_img)

                    # 1. Vision et pré-traitement
                    preprocessed = preprocess_image(bgr_img, target_height=2400, apply_threshold=False)

                    # 2. OCR PaddleOCR
                    ocr_results = ocr_engine.extract_text_and_boxes(preprocessed)
                    if not ocr_results:
                        parsed_pages.append({
                            "filename": pdf_page_filename,
                            "invoice_type": invoice_type or "FOURNISSEUR",
                            "status": "A_VERIFIER",
                            "error_details": ["Aucun texte lisible détecté sur cette page."],
                            "serial_numbers": [],
                            "page_current": page_idx + 1,
                            "page_total": total_pdf_pages,
                            "created_at": datetime.now().isoformat(),
                        })
                        continue

                    # 3. Parsing de la page
                    p_data = parse_invoice(ocr_results, forced_type=invoice_type)
                    p_data["filename"] = pdf_page_filename
                    p_data["page_current"] = page_idx + 1
                    p_data["page_total"] = total_pdf_pages
                    parsed_pages.append(p_data)
            except Exception as e_pdf:
                logger.error("Erreur lors de la lecture du fichier PDF %s : %s", saved_path, e_pdf)
                raise HTTPException(status_code=400, detail=f"Erreur de lecture du PDF : {e_pdf}")
            continue

        # 1. Vision et pré-traitement (Images JPG / PNG / WEBP)
        preprocessed = preprocess_image(saved_path, target_height=2400, apply_threshold=False)

        # 2. OCR PaddleOCR
        ocr_results = ocr_engine.extract_text_and_boxes(preprocessed)
        if not ocr_results:
            parsed_pages.append({
                "filename": safe_filename,
                "invoice_type": invoice_type or "FOURNISSEUR",
                "status": "A_VERIFIER",
                "error_details": ["Aucun texte lisible détecté sur cette page."],
                "serial_numbers": [],
                "page_current": idx,
                "page_total": len(uploaded_files),
                "created_at": datetime.now().isoformat(),
            })
            continue

        # 3. Parsing de la page
        p_data = parse_invoice(ocr_results, forced_type=invoice_type)
        p_data["filename"] = safe_filename
        parsed_pages.append(p_data)

    if not parsed_pages:
        raise HTTPException(status_code=400, detail="Échec de lecture des fichiers.")

    # 4. Assemblage multi-pages
    replaced_old_id = None
    if len(parsed_pages) > 1:
        # Plusieurs pages uploadées ensemble (ex: Page 1 + Page 2)
        record = consolidate_pages(parsed_pages)
    else:
        # Une seule page uploadée : vérifier si elle complète une facture existante en BDD
        record = parsed_pages[0]
        if record.get("page_total", 1) > 1 or record.get("page_current", 1) > 1:
            all_existing = db.get_all_invoices()
            for ex in all_existing:
                if are_pages_of_same_invoice(ex, record):
                    logger.info("Détection d'une page complémentaire pour la facture ID %s", ex.get("id"))
                    record = consolidate_pages([ex, record])
                    replaced_old_id = ex.get("id")
                    break

    # 5. Validation d'intégrité
    status, errors, unique_hash = validator.validate(record)
    record["status"] = status
    record["error_details"] = errors
    record["unique_hash"] = unique_hash

    # 6. Sauvegarde SQLite (nettoyage de l'ancienne version partielle si consolidée)
    if replaced_old_id is not None:
        try:
            db.delete_invoice(replaced_old_id)
        except Exception:
            pass
    db.save_invoice(record)

    return record


@app.post("/api/scan")
async def scan_invoice(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    invoice_type: Optional[str] = Form(None),
) -> JSONResponse:
    """
    Reçoit une ou plusieurs photos d'une facture individuelle,
    applique l'analyse complète et met à jour le fichier Excel.
    """
    uploaded_files: List[UploadFile] = []
    if files:
        uploaded_files.extend(files)
    if file and file not in uploaded_files:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni pour l'analyse.")

    try:
        record = process_uploaded_invoice_files(
            uploaded_files=uploaded_files,
            invoice_type=invoice_type,
            prefix="scan",
        )

        # Mise à jour de l'Excel avec onglet de réconciliation
        all_invoices = db.get_all_invoices()
        export_to_excel(all_invoices, output_path=EXCEL_PATH)

        # Diagnostic de rapprochement immédiat
        reconcil = reconcile_invoices(all_invoices)
        reconcil_status_by_sn = {
            item["serial_number"]: item for item in reconcil["items"]
        }
        reconciliation_feedback = []
        for sn in record.get("serial_numbers", []):
            match = reconcil_status_by_sn.get(sn)
            if match:
                reconciliation_feedback.append({
                    "serial_number": sn,
                    "status": match["status"],
                    "diagnostic": match["diagnostic"],
                    "ecart_ttc": match.get("ecart_ttc"),
                })

        record["reconciliation"] = reconciliation_feedback
        return JSONResponse(content=record)

    except Exception as exc:
        logger.exception("Erreur lors de l'analyse mobile : %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "status": "ERREUR",
                "error_details": [f"Erreur de traitement : {str(exc)}"],
            },
        )


@app.post("/api/compare")
async def compare_invoices_endpoint(
    vendor_file: Optional[UploadFile] = File(None),
    vendor_files: Optional[List[UploadFile]] = File(None),
    client_file: Optional[UploadFile] = File(None),
    client_files: Optional[List[UploadFile]] = File(None),
) -> JSONResponse:
    """
    Reçoit les photos de la Facture Fournisseur (Achat) et de la Facture Client (Vente).
    Traite les deux documents en parallèle ou séquentiellement,
    les enregistre et produit une comparaison 2 colonnes avec surlignage sémantique :
    - Vert (MATCH) : identique ou marge positive
    - Orange (WARNING) : tolérance OCR, marques équivalentes, TVA déduite
    - Rouge (ERROR) : appareil non refacturé, vente à perte, anomalie
    """
    v_uploads: List[UploadFile] = []
    if vendor_files:
        v_uploads.extend(vendor_files)
    if vendor_file and vendor_file not in v_uploads:
        v_uploads.append(vendor_file)

    c_uploads: List[UploadFile] = []
    if client_files:
        c_uploads.extend(client_files)
    if client_file and client_file not in c_uploads:
        c_uploads.append(client_file)

    if not v_uploads:
        raise HTTPException(
            status_code=400,
            detail="Veuillez fournir au moins un fichier pour la Facture Fournisseur (Achat).",
        )
    if not c_uploads:
        raise HTTPException(
            status_code=400,
            detail="Veuillez fournir au moins un fichier pour la Facture Client (Vente).",
        )

    try:
        # 1. Traitement Facture Fournisseur (Achat)
        vendor_record = process_uploaded_invoice_files(
            uploaded_files=v_uploads,
            invoice_type="FOURNISSEUR",
            prefix="fournisseur",
        )

        # 2. Traitement Facture Client (Vente)
        client_record = process_uploaded_invoice_files(
            uploaded_files=c_uploads,
            invoice_type="CLIENT",
            prefix="client",
        )

        # 3. Mise à jour automatique de la synthèse Excel
        all_invoices = db.get_all_invoices()
        export_to_excel(all_invoices, output_path=EXCEL_PATH)

        # 4. Comparaison directe des deux documents
        comparison_result = compare_invoices(vendor_record, client_record)
        return JSONResponse(content=comparison_result)

    except Exception as exc:
        logger.exception("Erreur lors de la comparaison des factures : %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "global_status": "ERROR",
                "summary": f"Erreur lors de la comparaison : {str(exc)}",
                "rows": [],
            },
        )




@app.get("/api/reconciliation")
async def get_reconciliation_report() -> JSONResponse:
    """Retourne l'état complet du rapprochement Fournisseur / Client par S/N."""
    all_invoices = db.get_all_invoices()
    report = reconcile_invoices(all_invoices)
    return JSONResponse(content=report)


@app.get("/api/invoices")
async def list_invoices() -> JSONResponse:
    invoices = db.get_all_invoices()
    return JSONResponse(content=invoices)


@app.get("/api/invoices/{invoice_id}")
async def get_single_invoice(invoice_id: int) -> JSONResponse:
    """Retourne les détails d'une facture spécifique."""
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Facture #{invoice_id} introuvable.")
    return JSONResponse(content=inv)


@app.put("/api/invoices/{invoice_id}")
async def update_single_invoice(
    invoice_id: int,
    updates: Dict[str, Any] = Body(...),
) -> JSONResponse:
    """
    Met à jour les données d'une facture (Human-in-the-Loop)
    et synchronise le classeur Excel et la base SQLite.
    """
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Facture #{invoice_id} introuvable.")

    # Nettoyage et normalisation des numéros de série si transmis en texte
    if "serial_numbers" in updates:
        val_sn = updates["serial_numbers"]
        if isinstance(val_sn, str):
            from core.post_corrector import clean_serial_number
            primary_tokens = [t.strip() for t in re.split(r"[,;\n\r]+", val_sn.strip()) if t.strip()]
            cleaned_list = []
            for t in primary_tokens:
                sub_parts = t.split()
                if len(sub_parts) > 1 and all(len(p) >= 6 for p in sub_parts):
                    for p in sub_parts:
                        c = clean_serial_number(p)
                        if c:
                            cleaned_list.append(c)
                else:
                    c = clean_serial_number(t)
                    if c:
                        cleaned_list.append(c)
            updates["serial_numbers"] = cleaned_list
        elif isinstance(val_sn, list):
            from core.post_corrector import clean_serial_number
            updates["serial_numbers"] = [clean_serial_number(str(tok)) for tok in val_sn if tok]

    # Nettoyage et normalisation des noms de produits si transmis
    if "product_names" in updates:
        val_pn = updates["product_names"]
        if isinstance(val_pn, str):
            prod_list = [p.strip() for p in re.split(r"[,;\n\r]+", val_pn.strip()) if p.strip()]
            updates["product_names"] = prod_list
        elif isinstance(val_pn, list):
            updates["product_names"] = [str(p).strip() for p in val_pn if str(p).strip()]

    # Re-calcul TVA automatique si HT et TTC fournis sans TVA
    if "montant_ht" in updates and "montant_ttc" in updates and "montant_tva" not in updates:
        try:
            ht = float(str(updates["montant_ht"]).replace(",", "."))
            ttc = float(str(updates["montant_ttc"]).replace(",", "."))
            updates["montant_tva"] = round(ttc - ht, 2)
        except Exception:
            pass

    success = db.update_invoice(invoice_id, updates)
    if not success:
        raise HTTPException(status_code=500, detail="Échec de la mise à jour de la facture.")

    # Synchronisation immédiate avec le classeur Excel
    all_invoices = db.get_all_invoices()
    export_to_excel(all_invoices, output_path=EXCEL_PATH)

    updated_inv = db.get_invoice_by_id(invoice_id)
    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Facture #{invoice_id} mise à jour avec succès.",
            "invoice": updated_inv,
        }
    )


@app.delete("/api/invoices/{invoice_id}")
async def delete_single_invoice(invoice_id: int) -> JSONResponse:
    """Supprime une facture individuelle par son ID et actualise la synthèse Excel."""
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Facture #{invoice_id} introuvable.")

    # Nettoyage des photos associées
    filename_raw = inv.get("filename") or ""
    parts = filename_raw.split(" + ")
    for part in parts:
        clean_fn = part.split(" ")[0].strip()
        fpath = INPUT_DIR / clean_fn
        if fpath.exists() and fpath.is_file():
            try:
                fpath.unlink()
            except Exception:
                pass

    success = db.delete_invoice(invoice_id)
    if not success:
        raise HTTPException(status_code=500, detail="Échec de la suppression en base de données.")

    # Mise à jour du classeur Excel
    all_invoices = db.get_all_invoices()
    export_to_excel(all_invoices, output_path=EXCEL_PATH)

    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Facture #{invoice_id} supprimée avec succès.",
            "remaining_count": len(all_invoices),
        }
    )


@app.delete("/api/invoices")
async def delete_all_invoices() -> JSONResponse:
    """Supprime toutes les factures enregistrées et réinitialise l'Excel."""
    all_invoices = db.get_all_invoices()
    for inv in all_invoices:
        filename_raw = inv.get("filename") or ""
        parts = filename_raw.split(" + ")
        for part in parts:
            clean_fn = part.split(" ")[0].strip()
            fpath = INPUT_DIR / clean_fn
            if fpath.exists() and fpath.is_file():
                try:
                    fpath.unlink()
                except Exception:
                    pass

    deleted_count = db.clear_all_invoices()
    export_to_excel([], output_path=EXCEL_PATH)

    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Toutes les factures ({deleted_count}) ont été supprimées.",
            "deleted_count": deleted_count,
        }
    )


@app.get("/api/export")
async def download_excel() -> FileResponse:
    all_invoices = db.get_all_invoices()
    export_to_excel(all_invoices, output_path=EXCEL_PATH)

    if not EXCEL_PATH.exists():
        raise HTTPException(status_code=404, detail="Classeur Excel introuvable.")

    return FileResponse(
        path=str(EXCEL_PATH),
        filename="factures_synthese.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/kpi")
async def get_kpis() -> JSONResponse:
    all_invoices = db.get_all_invoices()
    reconcil = reconcile_invoices(all_invoices)
    total = len(all_invoices)
    valides = sum(1 for i in all_invoices if i.get("status") == "VALIDE")

    return JSONResponse(
        content={
            "total_count": total,
            "valides_count": valides,
            "reconciliation": reconcil["kpi"],
        }
    )
