"""
Module d'export dynamique Excel avec openpyxl.
Génère un classeur professionnel avec :
1. Onglet "Tableau de Bord" (KPIs d'audit comptable et KPIs de réconciliation S/N).
2. Onglet "Rapprochement Prothèses (S/N)" (Corrélation Fournisseur <-> Client).
3. Onglet "Détail Factures" (Audit exhaustif avec mise en forme conditionnelle).
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json
import logging
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.reconciliation import reconcile_invoices

logger = logging.getLogger("FactureChecker.ExcelExport")

# Couleurs ARGB openpyxl
COLOR_HEADER_BG = "FF1B365D"       # Bleu nuit
COLOR_HEADER_FG = "FFFFFFFF"       # Blanc
COLOR_HEADER_SEC = "FF2C5282"      # Bleu acier

COLOR_VALID_BG = "FFD4EDDA"        # Vert clair
COLOR_VALID_FG = "FF155724"        # Vert foncé

COLOR_ERROR_BG = "FFF8D7DA"        # Rouge clair
COLOR_ERROR_FG = "FF721C24"        # Rouge foncé

COLOR_WARN_BG = "FFFFF3CD"         # Orange/Jaune clair
COLOR_WARN_FG = "FF856404"         # Orange foncé

COLOR_BORDER = "FFD0D5DD"          # Bordure grille fine


def get_status_style(status: str) -> Dict[str, Any]:
    status_upper = (status or "").upper()
    if status_upper in ("VALIDE", "RAPPROCHE"):
        fill = PatternFill(start_color=COLOR_VALID_BG, end_color=COLOR_VALID_BG, fill_type="solid")
        font = Font(name="Calibri", size=11, bold=True, color=COLOR_VALID_FG)
    elif status_upper in ("ERREUR_CALCUL", "SIRET_INVALIDE", "NON_REFACTURE"):
        fill = PatternFill(start_color=COLOR_ERROR_BG, end_color=COLOR_ERROR_BG, fill_type="solid")
        font = Font(name="Calibri", size=11, bold=True, color=COLOR_ERROR_FG)
    elif status_upper in ("DOUBLON", "A_VERIFIER", "ACHAT_NON_TROUVE"):
        fill = PatternFill(start_color=COLOR_WARN_BG, end_color=COLOR_WARN_BG, fill_type="solid")
        font = Font(name="Calibri", size=11, bold=True, color=COLOR_WARN_FG)
    else:
        fill = PatternFill(fill_type=None)
        font = Font(name="Calibri", size=11)

    return {"fill": fill, "font": font}


def format_error_details(errors_raw: Any) -> str:
    if not errors_raw:
        return ""
    if isinstance(errors_raw, str):
        try:
            parsed = json.loads(errors_raw)
            if isinstance(parsed, list):
                return " | ".join(str(e) for e in parsed)
        except Exception:
            return errors_raw
    elif isinstance(errors_raw, list):
        return " | ".join(str(e) for e in errors_raw)
    return str(errors_raw)


def format_serials_display(serials_raw: Any) -> str:
    if not serials_raw:
        return ""
    if isinstance(serials_raw, str):
        try:
            serials_raw = json.loads(serials_raw)
        except Exception:
            return serials_raw
    if isinstance(serials_raw, list):
        return ", ".join(str(s) for s in serials_raw)
    return str(serials_raw)


def export_to_excel(
    invoices: List[Dict[str, Any]],
    output_path: Union[str, Path] = "factures_synthese.xlsx",
) -> str:
    """
    Génère le classeur Excel d'audit et de rapprochement par numéro de série.
    """
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    thin_side = Side(border_style="thin", color=COLOR_BORDER)
    border_all = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    # Calcul de la réconciliation Fournisseur / Client
    reconcil_data = reconcile_invoices(invoices)
    reconciled_items = reconcil_data["items"]
    reconcil_kpi = reconcil_data["kpi"]

    # -------------------------------------------------------------
    # 1. Onglet Tableau de Bord (Synthèse globale & Rapprochement)
    # -------------------------------------------------------------
    ws_kpi = wb.active
    ws_kpi.title = "Tableau de Bord"
    _build_kpi_sheet(ws_kpi, invoices, reconcil_kpi)

    # -------------------------------------------------------------
    # 2. Onglet Rapprochement Prothèses (S/N)
    # -------------------------------------------------------------
    ws_reconcil = wb.create_sheet(title="Rapprochement Protheses SN")
    _build_reconciliation_sheet(ws_reconcil, reconciled_items, border_all)

    # -------------------------------------------------------------
    # 3. Onglet Détail Factures
    # -------------------------------------------------------------
    ws_data = wb.create_sheet(title="Détail Factures")
    _build_detail_sheet(ws_data, invoices, border_all)

    wb.save(str(out_file))
    logger.info("Export Excel dynamique généré avec succès : %s", out_file)
    return str(out_file)


def _build_kpi_sheet(ws, invoices: List[Dict[str, Any]], rec_kpi: Dict[str, Any]) -> None:
    ws.views.sheetView[0].showGridLines = True

    # Titre principal
    ws.merge_cells("A1:E1")
    title_cell = ws["A1"]
    title_cell.value = "AUDIT DES FACTURES & RAPPROCHEMENT PAR N° DE SÉRIE"
    title_cell.font = Font(name="Calibri", size=15, bold=True, color="FFFFFFFF")
    title_cell.fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 38

    ws["A2"] = f"Rapport généré le : {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
    ws["A2"].font = Font(name="Calibri", size=10, italic=True)

    header_fill = PatternFill(start_color="FFE9ECEF", end_color="FFE9ECEF", fill_type="solid")
    border = Border(
        left=Side(style="thin", color=COLOR_BORDER),
        right=Side(style="thin", color=COLOR_BORDER),
        top=Side(style="thin", color=COLOR_BORDER),
        bottom=Side(style="thin", color=COLOR_BORDER),
    )

    # Section 1 : KPIs Rapprochement Aides Auditives (S/N)
    ws.merge_cells("A4:C4")
    h_rec = ws["A4"]
    h_rec.value = "1. Rapprochement Dépenses Fournisseurs ↔ Refacturations Clients"
    h_rec.font = Font(name="Calibri", size=11, bold=True, color="FF1B365D")
    h_rec.fill = PatternFill(start_color="FFE2E8F0", end_color="FFE2E8F0", fill_type="solid")

    ws.merge_cells("D4:E4")
    h_rec_val = ws["D4"]
    h_rec_val.value = "Valeur"
    h_rec_val.font = Font(name="Calibri", size=11, bold=True, color="FF1B365D")
    h_rec_val.fill = PatternFill(start_color="FFE2E8F0", end_color="FFE2E8F0", fill_type="solid")
    h_rec_val.alignment = Alignment(horizontal="center")

    kpi_reconcil_items = [
        ("Total Numéros de Série (S/N) Détectés", rec_kpi.get("total_serials_detected", 0), "center", "#,##0"),
        ("Appareils Rapprochés (Achats = Ventes)", rec_kpi.get("rapproches_count", 0), "center", "#,##0"),
        ("Appareils Achetés NON REFACTURÉS (Perte potentielle)", rec_kpi.get("non_refactures_count", 0), "center", "#,##0"),
        ("Factures Achat Fabricant Manquantes", rec_kpi.get("achats_manquants_count", 0), "center", "#,##0"),
        ("Taux de Couverture des Appareils", rec_kpi.get("taux_couverture", 0.0) / 100.0, "center", "0.0%"),
        ("Volume Financier Achats Rapprochés (TTC)", rec_kpi.get("volume_achats_reconcilies", 0.0), "right", '#,##0.00 "€"'),
        ("Volume Financier Ventes Refacturées (TTC)", rec_kpi.get("volume_ventes_reconciliees", 0.0), "right", '#,##0.00 "€"'),
        ("Montant des Dépenses Non Refacturées (TTC)", rec_kpi.get("volume_dépenses_orphelines", 0.0), "right", '#,##0.00 "€"'),
        ("Solde Net de Réconciliation (Ventes - Achats)", rec_kpi.get("solde_net_reconcilie", 0.0), "right", '#,##0.00 "€"'),
    ]

    for i, (label, val, align_h, num_fmt) in enumerate(kpi_reconcil_items, start=5):
        ws.row_dimensions[i].height = 23
        ws.merge_cells(f"A{i}:C{i}")
        cell_lbl = ws[f"A{i}"]
        cell_lbl.value = label
        cell_lbl.font = Font(name="Calibri", size=10, bold=("NON REFACTURÉ" in label or "Solde Net" in label))
        if "NON REFACTURÉ" in label and val > 0:
            cell_lbl.font = Font(name="Calibri", size=10, bold=True, color="FF991B1B")
        cell_lbl.border = border

        ws.merge_cells(f"D{i}:E{i}")
        cell_val = ws[f"D{i}"]
        cell_val.value = val
        cell_val.font = Font(name="Calibri", size=10, bold=True)
        if "NON REFACTURÉ" in label and val > 0:
            cell_val.font = Font(name="Calibri", size=10, bold=True, color="FF991B1B")
            cell_val.fill = PatternFill(start_color=COLOR_ERROR_BG, end_color=COLOR_ERROR_BG, fill_type="solid")
        cell_val.alignment = Alignment(horizontal=align_h, vertical="center")
        cell_val.number_format = num_fmt
        cell_val.border = border

    # Section 2 : Conformité Documentaire & Audit Technique
    row_start_audit = 5 + len(kpi_reconcil_items) + 1
    ws.merge_cells(f"A{row_start_audit}:C{row_start_audit}")
    h_aud = ws[f"A{row_start_audit}"]
    h_aud.value = "2. Contrôles d'Intégrité Légale & Fiscale des Factures"
    h_aud.font = Font(name="Calibri", size=11, bold=True, color="FF1B365D")
    h_aud.fill = PatternFill(start_color="FFE2E8F0", end_color="FFE2E8F0", fill_type="solid")

    ws.merge_cells(f"D{row_start_audit}:E{row_start_audit}")
    h_aud_val = ws[f"D{row_start_audit}"]
    h_aud_val.value = "Nombre"
    h_aud_val.font = Font(name="Calibri", size=11, bold=True, color="FF1B365D")
    h_aud_val.fill = PatternFill(start_color="FFE2E8F0", end_color="FFE2E8F0", fill_type="solid")
    h_aud_val.alignment = Alignment(horizontal="center")

    total_count = len(invoices)
    valides = sum(1 for i in invoices if (i.get("status") or "").upper() == "VALIDE")
    erreurs_calc = sum(1 for i in invoices if (i.get("status") or "").upper() == "ERREUR_CALCUL")
    doublons = sum(1 for i in invoices if (i.get("status") or "").upper() == "DOUBLON")
    a_verifier = sum(1 for i in invoices if (i.get("status") or "").upper() in ("A_VERIFIER", "SIRET_INVALIDE"))

    kpi_audit_items = [
        ("Nombre Total de Factures Scannées", total_count, "center", "#,##0"),
        ("Factures Conformes (VALIDE)", valides, "center", "#,##0"),
        ("Erreurs Arithmétiques (ERREUR_CALCUL)", erreurs_calc, "center", "#,##0"),
        ("Factures À Vérifier (A_VERIFIER)", a_verifier, "center", "#,##0"),
        ("Doublons Détectés (DOUBLON)", doublons, "center", "#,##0"),
    ]

    for i, (label, val, align_h, num_fmt) in enumerate(kpi_audit_items, start=row_start_audit + 1):
        ws.row_dimensions[i].height = 22
        ws.merge_cells(f"A{i}:C{i}")
        cell_lbl = ws[f"A{i}"]
        cell_lbl.value = label
        cell_lbl.font = Font(name="Calibri", size=10)
        cell_lbl.border = border

        ws.merge_cells(f"D{i}:E{i}")
        cell_val = ws[f"D{i}"]
        cell_val.value = val
        cell_val.font = Font(name="Calibri", size=10, bold=True)
        cell_val.alignment = Alignment(horizontal=align_h, vertical="center")
        cell_val.number_format = num_fmt
        cell_val.border = border

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16


def _build_reconciliation_sheet(ws, items: List[Dict[str, Any]], border_all: Border) -> None:
    ws.views.sheetView[0].showGridLines = True

    columns = [
        ("N° Série (S/N)", 18, "center", "@"),
        ("Appareil / Modèle", 25, "left", "@"),
        ("Statut Rapprochement", 20, "center", "@"),
        ("Diagnostic & Écart", 35, "left", "@"),
        ("Fabricant / Fournisseur", 22, "left", "@"),
        ("N° Facture Achat", 16, "center", "@"),
        ("Date Achat", 13, "center", "YYYY-MM-DD"),
        ("Prix Achat HT", 15, "right", '#,##0.00 "€"'),
        ("Prix Achat TTC", 15, "right", '#,##0.00 "€"'),
        ("Patient / Client", 22, "left", "@"),
        ("N° Facture Vente", 16, "center", "@"),
        ("Date Vente", 13, "center", "YYYY-MM-DD"),
        ("Prix Vente HT", 15, "right", '#,##0.00 "€"'),
        ("Prix Vente TTC", 15, "right", '#,##0.00 "€"'),
        ("Écart / Marge TTC", 16, "right", '#,##0.00 "€"'),
        ("Fichier Achat", 24, "left", "@"),
        ("Fichier Vente", 24, "left", "@"),
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color=COLOR_HEADER_FG)
    header_fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.row_dimensions[1].height = 28
    for col_idx, (col_name, _, _, _) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border_all

    for row_idx, item in enumerate(items, start=2):
        ws.row_dimensions[row_idx].height = 22
        status = item.get("status", "ACHAT_NON_TROUVE")
        style = get_status_style(status)

        achat_ht = item.get("achat_prix_ht")
        achat_ttc = item.get("achat_prix_ttc")
        vente_ht = item.get("vente_prix_ht")
        vente_ttc = item.get("vente_prix_ttc")
        ecart = item.get("ecart_ttc")

        row_values = [
            item.get("serial_number"),
            item.get("produit_nom") or "-",
            status,
            item.get("diagnostic"),
            item.get("fournisseur_nom") or "-",
            item.get("achat_num_facture") or "-",
            item.get("achat_date") or "-",
            achat_ht if achat_ht is not None else "-",
            achat_ttc if achat_ttc is not None else "-",
            item.get("patient_nom") or "-",
            item.get("vente_num_facture") or "-",
            item.get("vente_date") or "-",
            vente_ht if vente_ht is not None else "-",
            vente_ttc if vente_ttc is not None else "-",
            ecart if ecart is not None else "-",
            item.get("achat_fichier") or "-",
            item.get("vente_fichier") or "-",
        ]

        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            col_align_h = columns[col_idx - 1][2]
            col_number_format = columns[col_idx - 1][3]

            cell.fill = style["fill"]
            if col_idx == 3:  # Statut
                cell.font = style["font"]
            else:
                cell.font = Font(name="Calibri", size=10)

            cell.alignment = Alignment(horizontal=col_align_h, vertical="center")
            if isinstance(val, (int, float)):
                cell.number_format = col_number_format
            else:
                cell.number_format = "@"
                if val == "-":
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border_all

    for col_idx, (_, default_width, _, _) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = default_width

    if items:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(items) + 1}"
    ws.freeze_panes = "A2"


def _build_detail_sheet(ws, invoices: List[Dict[str, Any]], border_all: Border) -> None:
    ws.views.sheetView[0].showGridLines = True

    columns = [
        ("N°", 6, "center", "@"),
        ("Type de Facture", 16, "center", "@"),
        ("N° Facture", 16, "center", "@"),
        ("Date Émission", 14, "center", "YYYY-MM-DD"),
        ("Fabricant / Fournisseur", 24, "left", "@"),
        ("Patient / Client", 24, "left", "@"),
        ("Appareils Détectés (S/N)", 26, "center", "@"),
        ("Produits / Modèles", 26, "left", "@"),
        ("Montant HT", 15, "right", '#,##0.00 "€"'),
        ("Montant TVA", 15, "right", '#,##0.00 "€"'),
        ("Montant TTC", 15, "right", '#,##0.00 "€"'),
        ("Statut Audit", 16, "center", "@"),
        ("Observations / Détails", 40, "left", "@"),
        ("Fichier Source", 28, "left", "@"),
        ("Date Numérisation", 18, "center", "YYYY-MM-DD HH:MM"),
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color=COLOR_HEADER_FG)
    header_fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.row_dimensions[1].height = 28
    for col_idx, (col_name, _, _, _) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border_all

    for row_idx, inv in enumerate(invoices, start=2):
        ws.row_dimensions[row_idx].height = 22
        status = inv.get("status", "A_VERIFIER")
        style = get_status_style(status)

        error_text = format_error_details(inv.get("error_details"))
        serials_text = format_serials_display(inv.get("serial_numbers"))

        prod_names = inv.get("product_names") or []
        if isinstance(prod_names, str):
            import json
            try:
                prod_names = json.loads(prod_names)
            except Exception:
                prod_names = [prod_names]
        products_text = ", ".join(prod_names) if isinstance(prod_names, list) else str(prod_names)

        created_at_raw = inv.get("created_at", "")
        if created_at_raw and "T" in created_at_raw:
            created_at_fmt = created_at_raw.replace("T", " ")[:16]
        else:
            created_at_fmt = str(created_at_raw)[:16]

        raw_type = (inv.get("invoice_type") or "FOURNISSEUR").upper()
        type_display = "Vente Patient" if raw_type == "CLIENT" else "Achat Fabricant"

        fournisseur_disp = inv.get("fournisseur_nom") or "-"
        patient_disp = inv.get("patient_nom") or "-"
        num_fac_disp = inv.get("numero_facture") or "-"
        date_fac_disp = inv.get("date_facture") or "-"

        m_ht = inv.get("montant_ht")
        m_tva = inv.get("montant_tva")
        m_ttc = inv.get("montant_ttc")

        row_values = [
            inv.get("id", row_idx - 1),
            type_display,
            num_fac_disp,
            date_fac_disp,
            fournisseur_disp,
            patient_disp,
            serials_text or "-",
            products_text or "-",
            m_ht if m_ht is not None else "-",
            m_tva if m_tva is not None else "-",
            m_ttc if m_ttc is not None else "-",
            status,
            error_text or "Conforme",
            inv.get("filename", ""),
            created_at_fmt,
        ]

        for col_idx, val in enumerate(row_values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            col_align_h = columns[col_idx - 1][2]
            col_number_format = columns[col_idx - 1][3]

            cell.fill = style["fill"]
            if col_idx == 12:  # Statut
                cell.font = style["font"]
            else:
                cell.font = Font(name="Calibri", size=10)

            cell.alignment = Alignment(horizontal=col_align_h, vertical="center", wrap_text=(col_idx == 13))
            if isinstance(val, (int, float)):
                cell.number_format = col_number_format
            else:
                cell.number_format = "@"
                if val == "-":
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border_all

    for col_idx, (_, default_width, _, _) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = default_width

    if invoices:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(invoices) + 1}"
    ws.freeze_panes = "A2"

