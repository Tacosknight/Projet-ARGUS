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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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
ocr_engine = OCREngine(lang="fr", use_angle_cls=True)


@app.get("/", response_class=HTMLResponse)
async def serve_mobile_ui() -> HTMLResponse:
    index_file = Path(__file__).parent / "templates" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Facture-Checker Web UI</h1>")


@app.post("/api/scan")
async def scan_invoice(
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    invoice_type: Optional[str] = Form(None),
) -> JSONResponse:
    """
    Reçoit une ou plusieurs photos de facture (mono ou multi-pages),
    applique le pré-traitement, l'OCR, la consolidation multi-pages,
    l'extraction des S/N et le rapprochement financier.
    """
    uploaded_files: List[UploadFile] = []
    if files:
        uploaded_files.extend(files)
    if file and file not in uploaded_files:
        uploaded_files.append(file)

    if not uploaded_files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni pour l'analyse.")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed_pages: List[Dict[str, Any]] = []

    try:
        for idx, ufile in enumerate(uploaded_files, 1):
            if not ufile.filename:
                continue
            safe_filename = f"scan_{timestamp_str}_p{idx}_{Path(ufile.filename).name}"
            saved_path = INPUT_DIR / safe_filename

            with saved_path.open("wb") as buffer:
                shutil.copyfileobj(ufile.file, buffer)

            # 1. Vision et pré-traitement
            preprocessed = preprocess_image(saved_path, target_height=1600, apply_threshold=True)

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

        # 7. Mise à jour de l'Excel avec onglet de réconciliation
        all_invoices = db.get_all_invoices()
        export_to_excel(all_invoices, output_path=EXCEL_PATH)

        # 8. Diagnostic de rapprochement immédiat
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
