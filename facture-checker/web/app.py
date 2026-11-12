"""
Application Web FastAPI Mobile-First pour Facture-Checker.
Permet de photographier une facture (Achat Fabricant ou Vente Patient)
avec la caméra du smartphone, d'extraire les numéros de série (S/N),
d'analyser l'intégrité légale et de suivre le rapprochement financier en temps réel.
"""

from datetime import datetime
import json
import hashlib
import logging
from pathlib import Path
import shutil
import os
import platform
import sys
import sqlite3
import zipfile
import tempfile
from functools import wraps
from uuid import uuid4
from typing import Any, Dict, List, Optional
import re
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile, Request
from starlette.background import BackgroundTask
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
from core.app_paths import (
    DATABASE_PATH,
    EXCEL_PATH,
    INPUT_DIR,
    MODELS_DIR,
    DATA_DIR,
    ensure_app_directories,
)
from core.document_loader import iter_document_pages
from core.pdf_native import native_pdf_page
from storage.database import InvoiceDatabase
from storage.export_excel import export_to_excel
from storage.backup import apply_restore, extract_backup, snapshot_sqlite, RecoveryError
from core.data_lock import DATA_LOCK

logger = logging.getLogger("FactureChecker.Web")

app = FastAPI(
    title="Facture-Checker Mobile",
    description="Scanner et auditeur de factures d'aides auditives avec rapprochement S/N.",
    version="2.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
ensure_app_directories()
DB_PATH = DATABASE_PATH

# Instances partagées
db = InvoiceDatabase(str(DB_PATH))
validator = InvoiceValidator(db_is_duplicate_fn=db.is_hash_exists)
ocr_engine = OCREngine(lang="fr")



def serialized_data(function):
    """Routes sans await interne : protéger aussi les fichiers et les snapshots."""
    @wraps(function)
    async def locked(*args, **kwargs):
        with DATA_LOCK:
            return await function(*args, **kwargs)
    return locked


def refresh_excel(invoices: List[Dict[str, Any]]) -> List[str]:
    try:
        export_to_excel(invoices, output_path=EXCEL_PATH)
        return []
    except Exception:
        # La transaction métier est déjà validée : ne pas inviter à la répéter.
        logger.warning("Export Excel différé (%s).", sys.exc_info()[0].__name__)
        return ["Données enregistrées ; export Excel non actualisé. Fermez Excel puis relancez l'export."]


@app.get("/", response_class=HTMLResponse)
async def serve_mobile_ui() -> HTMLResponse:
    index_file = Path(__file__).parent / "templates" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Facture-Checker Web UI</h1>")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok", "version": app.version})


def process_uploaded_invoice_files(
    uploaded_files: List[UploadFile],
    invoice_type: Optional[str] = None,
    prefix: str = "scan",
    merge_existing: bool = True,
    direct_upload_fingerprint: Optional[str] = None,
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
    extraction_pages: List[Dict[str, Any]] = []

    for idx, ufile in enumerate(uploaded_files, 1):
        if not ufile.filename:
            continue
        original_name = Path(ufile.filename).name
        safe_name = re.sub(r"[^\w.()' -]+", "_", original_name, flags=re.UNICODE).strip(" .")
        safe_filename = f"{prefix}_{timestamp_str}_p{idx}_{safe_name or 'document'}"
        saved_path = INPUT_DIR / safe_filename
        source_documents = [{"filename": safe_filename, "original_name": original_name}]

        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(ufile.file, buffer)

        try:
            pages = iter_document_pages(saved_path)
            for page_number, page_total, bgr_img in pages:
                page_filename = safe_filename
                if saved_path.suffix.lower() == ".pdf":
                    page_filename = f"{prefix}_{timestamp_str}_f{idx}_p{page_number}.jpg"
                    encoded_ok, encoded = cv2.imencode(".jpg", bgr_img)
                    if not encoded_ok:
                        raise OSError("Impossible d'encoder la page PDF en image.")
                    (INPUT_DIR / page_filename).write_bytes(encoded.tobytes())
                ocr_results = None
                if saved_path.suffix.lower() == ".pdf":
                    try:
                        ocr_results, reason = native_pdf_page(saved_path, page_number)
                        logger.info("Extraction PDF page %d : %s", page_number, "texte natif" if ocr_results else "OCR")
                    except Exception:
                        logger.warning("Extraction PDF native indisponible sur la page %d ; OCR utilisé.", page_number)
                source = "pdf_text" if ocr_results else "ocr"
                if not ocr_results:
                    preprocessed = preprocess_image(bgr_img, target_height=2400, apply_threshold=False)
                    ocr_results = ocr_engine.extract_text_and_boxes(preprocessed)
                extraction_pages.append({"document": idx, "page": page_number, "total": page_total, "source": source, "text_detected": bool(ocr_results)})
                if not ocr_results:
                    parsed_pages.append({
                        "filename": page_filename,
                        "source_documents": source_documents,
                        "invoice_type": invoice_type or "FOURNISSEUR",
                        "marque_client": "Phoneme" if invoice_type == "CLIENT" else None,
                        "status": "A_VERIFIER",
                        "error_details": ["Aucun texte lisible détecté sur cette page."],
                        "serial_numbers": [],
                        "page_current": page_number,
                        "page_total": page_total,
                        "created_at": datetime.now().isoformat(),
                    })
                    continue
                p_data = parse_invoice(ocr_results, forced_type=invoice_type)
                p_data["filename"] = page_filename
                p_data["source_documents"] = source_documents
                p_data["page_current"] = page_number
                p_data["page_total"] = page_total
                parsed_pages.append(p_data)
        except RuntimeError as document_error:
            raise HTTPException(status_code=503, detail=str(document_error)) from document_error
        except Exception as document_error:
            logger.warning("Document non traité (%s).", type(document_error).__name__)
            raise HTTPException(status_code=400, detail=f"Document illisible : {document_error}") from document_error

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
        if merge_existing and (record.get("page_total", 1) > 1 or record.get("page_current", 1) > 1):
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
    record["error_details"] = list(dict.fromkeys(record.get("error_details", []) + errors))
    record["unique_hash"] = unique_hash

    # 6. Sauvegarde SQLite (nettoyage de l'ancienne version partielle si consolidée)
    if replaced_old_id is not None:
        try:
            db.delete_invoice(replaced_old_id)
        except Exception:
            pass
    if direct_upload_fingerprint:
        record["direct_upload_fingerprint"] = direct_upload_fingerprint
    record["id"] = db.save_invoice(record)
    # Informations de traitement transitoires : ne modifient pas le schéma historique.
    record["extraction_pages"] = extraction_pages

    return record


@app.post("/api/scan")
@serialized_data
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
        warnings = refresh_excel(all_invoices)

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
        record["warnings"] = warnings
        return JSONResponse(content=record)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Échec analyse mobile (%s).", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "status": "ERREUR",
                "error_details": [f"Erreur de traitement : {str(exc)}"],
            },
        )


@app.post("/api/compare")
@serialized_data
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
        warnings = refresh_excel(all_invoices)

        # 4. Comparaison directe des deux documents
        comparison_result = compare_invoices(vendor_record, client_record)
        comparison_result["vendor_extraction_pages"] = vendor_record.get("extraction_pages", [])
        comparison_result["client_extraction_pages"] = client_record.get("extraction_pages", [])
        comparison_result["warnings"] = warnings
        comparison_result["vendor_documents"] = invoice_documents(vendor_record)
        comparison_result["client_documents"] = invoice_documents(client_record)
        comparison_result["vendor_invoice_id"] = vendor_record["id"]
        comparison_result["client_invoice_id"] = client_record["id"]
        return JSONResponse(content=comparison_result)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Échec comparaison (%s).", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "global_status": "ERROR",
                "summary": f"Erreur lors de la comparaison : {str(exc)}",
                "rows": [],
            },
        )




@app.post("/api/compare-grouped")
@serialized_data
async def compare_grouped(request: Request) -> JSONResponse:
    """Multipart : vendor_files, client_0, client_1… ; chaque champ est une facture."""
    form = await request.form()
    keys = sorted((key for key in form.keys() if re.fullmatch(r"client_\d+", key)), key=lambda k: int(k[7:]))
    groups = [("fournisseur", "FOURNISSEUR", form.getlist("vendor_files"))]
    groups += [(key, "CLIENT", form.getlist(key)) for key in keys]
    if not keys or any(not files or any(not getattr(f, "filename", None) for f in files) for _, _, files in groups):
        raise HTTPException(400, "Fournissez une facture fournisseur et au moins un groupe client non vide.")

    results, records, seen = [], [], set()
    for key, kind, files in groups:
        try:
            digest = hashlib.sha256(kind.encode())
            for upload in files:
                upload.file.seek(0)
                content_hash = hashlib.sha256()
                for chunk in iter(lambda: upload.file.read(1024 * 1024), b""):
                    content_hash.update(chunk)
                upload.file.seek(0)
                digest.update(content_hash.digest())
            fingerprint = digest.hexdigest()
            if fingerprint in seen:
                raise HTTPException(400, "Ce groupe est identique à un autre groupe du dossier.")
            seen.add(fingerprint)
            record = db.get_direct_upload(fingerprint)
            reused = record is not None
            if not record:
                record = process_uploaded_invoice_files(files, invoice_type=kind, prefix=key,
                                                        merge_existing=False, direct_upload_fingerprint=fingerprint)
            records.append(record)
            results.append({"group": key, "invoice_id": record["id"], "reused": reused, "status": "enregistré"})
        except Exception as exc:
            logger.warning("Groupe %s non traité (%s)", key, type(exc).__name__)
            detail = exc.detail if isinstance(exc, HTTPException) else "Erreur de traitement du document."
            results.append({"group": key, "status": "échec", "error": str(detail)})
    complete = len(records) == len(groups)
    warnings = refresh_excel(db.get_all_invoices()) if records else []
    return JSONResponse({"complete": complete, "groups": results,
                         "reconciliation": reconcile_invoices(records) if complete else None,
                         "warnings": warnings})


@app.get("/api/reconciliation")
async def get_reconciliation_report() -> JSONResponse:
    """Retourne l'état complet du rapprochement Fournisseur / Client par S/N."""
    all_invoices = db.get_all_invoices()
    report = reconcile_invoices(all_invoices)
    return JSONResponse(content=report)


@app.get("/api/invoices")
async def list_invoices() -> JSONResponse:
    invoices = db.get_all_invoices()
    for invoice in invoices:
        invoice["source_documents"] = invoice_documents(invoice)
    return JSONResponse(content=invoices)


def invoice_documents(invoice: Dict[str, Any]) -> List[Dict[str, str]]:
    """Compatibilité avec les imports antérieurs à la traçabilité des originaux."""
    documents = invoice.get("source_documents") or []
    if documents:
        return documents
    names = re.sub(r" \(\d+ pages\)$", "", invoice.get("filename", "")).split(" + ")
    return [{"filename": name, "original_name": name} for name in names if name]


@app.get("/api/invoices/{invoice_id}/documents/{document_index}")
async def view_invoice_document(invoice_id: int, document_index: int) -> FileResponse:
    invoice = db.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable.")
    documents = invoice_documents(invoice)
    if document_index < 0 or document_index >= len(documents):
        raise HTTPException(status_code=404, detail="Document introuvable.")
    document = documents[document_index]
    root = INPUT_DIR.resolve()
    path = (root / document["filename"]).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier original indisponible.")
    if path.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
        raise HTTPException(status_code=415, detail="Format non visualisable.")
    return FileResponse(path, filename=document.get("original_name") or path.name,
                        content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


@app.get("/api/invoices/{invoice_id}")
async def get_single_invoice(invoice_id: int) -> JSONResponse:
    """Retourne les détails d'une facture spécifique."""
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Facture #{invoice_id} introuvable.")
    return JSONResponse(content=inv)


@app.put("/api/invoices/{invoice_id}")
@serialized_data
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

    from core.post_corrector import clean_serial_number
    from storage.database import InvoiceConflict

    updates = dict(updates)
    for field in ("emetteur_nom", "marque_produit"):
        if field in updates:
            if updates[field] is not None and not isinstance(updates[field], str):
                raise HTTPException(status_code=400, detail=f"Valeur invalide pour {field}.")
            updates[field] = (updates[field] or "").strip() or None
    expected_revision = updates.pop("expected_revision", None)
    if expected_revision is not None and (not isinstance(expected_revision, str) or not expected_revision):
        raise HTTPException(status_code=400, detail="Révision invalide.")
    if expected_revision is not None and expected_revision != inv["revision"]:
        raise HTTPException(status_code=409, detail="La facture a été modifiée depuis son ouverture.")
    corrections = updates.pop("serial_corrections", None)
    if corrections is not None:
        if not expected_revision:
            raise HTTPException(status_code=400, detail="Révision initiale requise pour corriger les numéros.")
        if "serial_numbers" in updates or "product_items" in updates or not isinstance(corrections, list) or not corrections:
            raise HTTPException(status_code=400, detail="Corrections de numéros invalides ou contradictoires.")
        serials = list(inv.get("serial_numbers") or [])
        items = [dict(item) for item in (inv.get("product_items") or [])]
        original_count = len(serials)
        used_serials, used_items = set(), set()
        for correction in corrections:
            if not isinstance(correction, dict) or set(correction) != {"serial_index", "item_indices", "value"}:
                raise HTTPException(status_code=400, detail="Correction de numéro invalide.")
            index, indices, value = correction["serial_index"], correction["item_indices"], correction["value"]
            if index is not None and (type(index) is not int or index < 0 or index >= original_count or index in used_serials):
                raise HTTPException(status_code=400, detail="Index de numéro invalide.")
            if not isinstance(indices, list) or any(type(i) is not int or i < 0 or i >= len(items) or i in used_items for i in indices) or len(set(indices)) != len(indices):
                raise HTTPException(status_code=400, detail="Indices de lignes invalides.")
            if not isinstance(value, str) or not value.strip() or not (cleaned := clean_serial_number(value)):
                raise HTTPException(status_code=400, detail="Numéro de série invalide.")
            old = serials[index] if index is not None else None
            if any((items[i].get("serial_number") or None) != old for i in indices):
                raise HTTPException(status_code=400, detail="La ligne sélectionnée ne correspond pas au numéro initial.")
            if old and any(item.get("serial_number") == old for item in items) and not indices:
                raise HTTPException(status_code=400, detail="Sélectionnez explicitement les lignes à corriger.")
            if index is not None:
                used_serials.add(index)
                serials[index] = cleaned
            else:
                serials.append(cleaned)
            for i in indices:
                used_items.add(i)
                items[i]["serial_number"] = cleaned
            if old and any(item.get("serial_number") == old for item in items) and old not in serials:
                serials.append(old)
        updates["serial_numbers"] = serials
        updates["product_items"] = items
    elif "serial_numbers" in updates:
        val = updates["serial_numbers"]
        if isinstance(val, str):
            val = [t.strip() for t in re.split(r"[,;\n\r]+", val) if t.strip()]
        if not isinstance(val, list) or any(not isinstance(t, str) or not t.strip() for t in val):
            raise HTTPException(status_code=400, detail="Liste de numéros invalide.")
        cleaned = [clean_serial_number(t) for t in val]
        if any(not t for t in cleaned):
            raise HTTPException(status_code=400, detail="Numéro de série invalide.")
        old = inv.get("serial_numbers") or []
        if any(item.get("serial_number") and item.get("serial_number") in old and item.get("serial_number") not in cleaned for item in (inv.get("product_items") or [])):
            raise HTTPException(status_code=400, detail="Sélectionnez explicitement les lignes à corriger.")
        updates["serial_numbers"] = cleaned
    if "product_items" in updates and corrections is None:
        incoming = updates["product_items"]
        existing = inv.get("product_items") or []
        if not isinstance(incoming, list) or any(not isinstance(item, dict) for item in incoming):
            raise HTTPException(status_code=400, detail="Liste de lignes produits invalide.")
        if incoming != existing:
            # Sans identifiant de ligne, seule une association unique par numéro ou
            # nom inchangé permet de fusionner sans perdre les métadonnées cachées.
            merged, used = [], set()
            serials = list(updates.get("serial_numbers", inv.get("serial_numbers") or []))
            for item in incoming:
                serial = item.get("serial_number") or None
                name = item.get("product_name") or item.get("designation") or ""
                if serial is not None:
                    if not isinstance(serial, str) or not (serial := clean_serial_number(serial)):
                        raise HTTPException(status_code=400, detail="Numéro de ligne produit invalide.")
                candidates = [i for i, old in enumerate(existing) if i not in used and serial and old.get("serial_number") == serial]
                if not candidates:
                    candidates = [i for i, old in enumerate(existing) if i not in used and name and (old.get("product_name") or old.get("designation") or "") == name]
                if len(candidates) > 1:
                    raise HTTPException(status_code=400, detail="Association de ligne produit ambiguë ; utilisez la correction explicite des numéros.")
                if candidates:
                    index = candidates[0]
                    old = existing[index]
                    if (old.get("serial_number") or None) != serial:
                        raise HTTPException(status_code=400, detail="Pour modifier le numéro d'une ligne, utilisez la correction explicite.")
                    used.add(index)
                    merged.append({**old, **item, "serial_number": serial})
                else:
                    merged.append({**item, "serial_number": serial})
                if serial and serial not in serials:
                    serials.append(serial)
            if len(used) != len(existing):
                raise HTTPException(status_code=400, detail="Impossible d'associer ou supprimer une ligne produit sans sélection explicite.")
            updates["product_items"] = merged
            updates["serial_numbers"] = serials
        else:
            del updates["product_items"]

    # Nettoyage et normalisation des noms de produits si transmis
    if "product_names" in updates:
        val_pn = updates["product_names"]
        if isinstance(val_pn, str):
            prod_list = [p.strip() for p in re.split(r"[,;\n\r]+", val_pn.strip()) if p.strip()]
            updates["product_names"] = prod_list
        elif isinstance(val_pn, list):
            updates["product_names"] = [str(p).strip() for p in val_pn if str(p).strip()]

    if "document_type" in updates:
        updates["document_type"] = str(updates["document_type"] or "FACTURE").upper()
        if updates["document_type"] not in {"FACTURE", "AVOIR"}:
            raise HTTPException(status_code=400, detail="Type de document invalide.")
    if "related_invoice_id" in updates:
        related = updates["related_invoice_id"]
        if related in (None, "", 0, "0"):
            updates["related_invoice_id"] = None
        else:
            try:
                related_id = int(related)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Facture d'origine invalide.") from exc
            if related_id == invoice_id or not db.get_invoice_by_id(related_id):
                raise HTTPException(status_code=400, detail="Facture d'origine introuvable.")
            updates["related_invoice_id"] = related_id

    # Re-calcul TVA automatique si HT et TTC fournis sans TVA
    if "montant_ht" in updates and "montant_ttc" in updates and "montant_tva" not in updates:
        try:
            ht = float(str(updates["montant_ht"]).replace(",", "."))
            ttc = float(str(updates["montant_ttc"]).replace(",", "."))
            updates["montant_tva"] = round(ttc - ht, 2)
        except Exception:
            pass

    try:
        success = db.update_invoice(invoice_id, updates, expected_revision=expected_revision)
    except InvoiceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=500, detail="Échec de la mise à jour de la facture.")

    # Synchronisation immédiate avec le classeur Excel
    try:
        warnings = refresh_excel(db.get_all_invoices())
    except Exception:
        logger.exception("Échec de synchronisation Excel après enregistrement.")
        warnings = ["Données enregistrées ; export Excel non actualisé."]

    updated_inv = db.get_invoice_by_id(invoice_id)
    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Facture #{invoice_id} mise à jour avec succès.",
            "invoice": updated_inv,
            "warnings": warnings,
        }
    )


@app.delete("/api/invoices/{invoice_id}")
@serialized_data
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
    warnings = refresh_excel(all_invoices)

    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Facture #{invoice_id} supprimée avec succès.",
            "remaining_count": len(all_invoices),
            "warnings": warnings,
        }
    )


@app.delete("/api/invoices")
@serialized_data
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
    warnings = refresh_excel([])

    return JSONResponse(
        content={
            "status": "OK",
            "message": f"Toutes les factures ({deleted_count}) ont été supprimées.",
            "deleted_count": deleted_count,
            "warnings": warnings,
        }
    )


@app.get("/api/export")
@serialized_data
async def download_excel() -> FileResponse:
    all_invoices = db.get_all_invoices()
    if refresh_excel(all_invoices):
        raise HTTPException(status_code=503, detail="Export impossible. Fermez Excel puis réessayez.")

    if not EXCEL_PATH.exists():
        raise HTTPException(status_code=404, detail="Classeur Excel introuvable.")

    # Un instantané unique évite qu'un export suivant remplace le fichier pendant
    # son envoi ; le handle de téléchargement n'empêche pas la restauration.
    with tempfile.NamedTemporaryFile(dir=EXCEL_PATH.parent, suffix=".xlsx", delete=False) as handle:
        download = Path(handle.name)
    try:
        shutil.copy2(EXCEL_PATH, download)
    except OSError:
        download.unlink(missing_ok=True)
        raise
    return FileResponse(
        path=str(download),
        filename="factures_synthese.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(download.unlink, missing_ok=True),
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


@app.get("/api/diagnostics")
async def get_diagnostics() -> JSONResponse:
    """Autodiagnostic local, sans inclure de données de facture ou de patient."""
    checks: List[Dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        ensure_app_directories()
        probe = DATA_DIR / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add_check("Dossier de données", True, str(DATA_DIR))
    except Exception as exc:
        add_check("Dossier de données", False, str(exc))

    try:
        db.get_connection().close()
        add_check("Base SQLite", True, str(DB_PATH))
    except Exception as exc:
        add_check("Base SQLite", False, str(exc))

    try:
        import pypdfium2  # noqa: F401
        add_check("Lecture PDF", True, "pypdfium2 disponible")
    except Exception as exc:
        add_check("Lecture PDF", False, str(exc))

    from core.ocr_models import validate_ocr_models
    validation = validate_ocr_models(MODELS_DIR)
    add_check(
        "Modèles OCR hors ligne",
        validation.is_valid,
        (f"Fichiers et noms vérifiés dans {MODELS_DIR} ; chargement réel non vérifié"
         if validation.is_valid else validation.error_message()),
    )

    disk = shutil.disk_usage(DATA_DIR)
    add_check("Espace disque", disk.free >= 500 * 1024 * 1024, f"{disk.free // (1024 * 1024)} Mo libres")
    return JSONResponse(content={
        "status": "OK" if all(item["ok"] for item in checks) else "ATTENTION",
        "version": app.version,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "checks": checks,
    })


@app.get("/api/backup")
@serialized_data
async def download_backup() -> FileResponse:
    """Crée une sauvegarde locale complète à conserver dans un emplacement sûr."""
    ensure_app_directories()
    backup_path = EXCEL_PATH.parent / f"ARGUS_sauvegarde_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.zip"
    with tempfile.TemporaryDirectory(dir=DATA_DIR, prefix=".backup-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, archive_name in (
                (DB_PATH, "data/invoices.db"),
                (DATA_DIR / "data" / "ocr_cache.db", "data/ocr_cache.db"),
            ):
                if path.is_file():
                    destination = snapshot / path.name
                    snapshot_sqlite(path, destination)
                    archive.write(destination, archive_name)
            if EXCEL_PATH.is_file():
                archive.write(EXCEL_PATH, "exports/factures_synthese.xlsx")
            for document in INPUT_DIR.rglob("*"):
                if document.is_file():
                    archive.write(document, f"imports/{document.relative_to(INPUT_DIR).as_posix()}")
    return FileResponse(backup_path, filename=backup_path.name, media_type="application/zip")


@app.post("/api/restore")
@serialized_data
async def restore_backup(file: UploadFile = File(...)) -> JSONResponse:
    """Restaure une archive produite par ARGUS après contrôles de sécurité."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Sélectionnez une sauvegarde ARGUS au format ZIP.")
    restore_dir = Path(tempfile.mkdtemp(dir=DATA_DIR, prefix=".restore-"))
    keep_recovery = False
    try:
        archive_path = restore_dir / "backup.zip"
        with archive_path.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        content = restore_dir / "content"
        candidate = extract_backup(archive_path, content)
        # Migrer/valider le schéma avant de remplacer les fichiers actifs.
        prepared_db = InvoiceDatabase(str(candidate))
        prepared_db.get_all_invoices()
        # Les accès DB/cache sont fermés explicitement et protégés par DATA_LOCK.
        apply_restore(content, Path(DB_PATH), DATA_DIR / "data" / "ocr_cache.db",
                      INPUT_DIR, restore_dir / "recovery")
    except RecoveryError as exc:
        keep_recovery = True
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (ValueError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=400, detail=f"Sauvegarde invalide : {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Restauration interrompue ; données précédentes conservées. Vérifiez les droits d'accès et réessayez.") from exc
    finally:
        if not keep_recovery:
            shutil.rmtree(restore_dir, ignore_errors=True)
    warnings = refresh_excel(db.get_all_invoices())
    return JSONResponse(content={"status": "OK", "message": "Sauvegarde restaurée avec succès.", "warnings": warnings})
