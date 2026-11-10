"""Sélection prudente du texte PDF natif, sans dépendance au moteur OCR.

Les boîtes sont exprimées dans le repère du rendu de document_loader (échelle
2, origine en haut à gauche). La confiance 1.0 est une convention de
compatibilité, pas une probabilité OCR. La provenance est aussi portée par
chaque bloc. Les heuristiques ne peuvent garantir qu'une couche est complète.
"""
from __future__ import annotations

import math
import unicodedata


PDF_RENDER_SCALE = 2.0


def native_pdf_page(path, page_number):
    """Retourne (blocs, 'native_pdf') ou (None, raison), page numérotée dès 1.

    Un rejet, y compris une erreur PDF, demande au consommateur de traiter la
    page entière par OCR ; aucun contenu du document n'est inclus dans la raison.
    """
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        return None, "invalid_page_number"
    document = None
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw

        document = pdfium.PdfDocument(str(path))
        if page_number > len(document):
            return None, "invalid_page_number"
        page = document[page_number - 1]
        try:
            left, bottom, right, top = page.get_bbox()
            w, h = right - left, top - bottom
            rotation = page.get_rotation()
            if not all(math.isfinite(v) for v in (left, bottom, right, top)) or w <= 0 or h <= 0 or rotation not in (0, 90, 180, 270):
                return None, "invalid_geometry"

            # Les lignes tournées ne peuvent pas être regroupées sans risquer
            # d'inverser l'ordre des caractères ou de fusionner des colonnes.
            if rotation:
                return None, "rotated_page"

            # Même une petite image peut contenir une donnée utile. Les formes
            # imbriquées ont leurs propres matrices et sont refusées par prudence.
            for obj in page.get_objects(max_depth=1):
                if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                    return None, "image_present"
                if obj.type == raw.FPDF_PAGEOBJ_FORM:
                    return None, "form_present"
                if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                    mode = raw.FPDFTextObj_GetTextRenderMode(obj.raw)
                    if mode not in (raw.FPDF_TEXTRENDERMODE_FILL, raw.FPDF_TEXTRENDERMODE_STROKE, raw.FPDF_TEXTRENDERMODE_FILL_STROKE):
                        return None, "invisible_or_clipped_text"

            textpage = page.get_textpage()
            try:
                chars = []
                invalid = 0
                total = 0
                for i in range(textpage.count_chars()):
                    code = raw.FPDFText_GetUnicode(textpage.raw, i)
                    if not code:
                        invalid += 1
                        continue
                    char = chr(code)
                    if char.isspace():
                        continue
                    total += 1
                    if unicodedata.category(char)[0] in ("C", "S") and not (char in "€£$%+×=°"):
                        invalid += 1
                        continue
                    l, b, r, t = textpage.get_charbox(i)
                    if not all(math.isfinite(v) for v in (l, b, r, t)) or r <= l or t <= b or l < left - 1 or r > right + 1 or b < bottom - 1 or t > top + 1:
                        invalid += 1
                        continue
                    # Canvas PDF (bas gauche) vers image tournée (haut gauche).
                    points = []
                    for x, y in ((l, b), (l, t), (r, b), (r, t)):
                        x, y = x - left, top - y
                        if rotation == 90:
                            x, y = h - y, x
                        elif rotation == 180:
                            x, y = w - x, h - y
                        elif rotation == 270:
                            x, y = y, w - x
                        points.append((x * PDF_RENDER_SCALE, y * PDF_RENDER_SCALE))
                    xs, ys = zip(*points)
                    chars.append((char, min(xs), min(ys), max(xs), max(ys)))
            finally:
                textpage.close()

            if total < 40 or len(chars) < 40:
                return None, "insufficient_text"
            if invalid > max(1, total * 0.02):
                return None, "invalid_text_or_geometry"
            if sum(c[0].isalnum() for c in chars) < len(chars) * 0.6:
                return None, "unreadable_text"

            # Grouper par lignes visuelles, puis séparer les colonnes largement
            # espacées. Les espaces ordinaires sont reconstitués géométriquement.
            chars.sort(key=lambda c: ((c[2] + c[4]) / 2, c[1]))
            lines = []
            for item in chars:
                cy = (item[2] + item[4]) / 2
                match = next((line for line in lines if abs(cy - line[0]) <= max(2.0, min(item[4] - item[2], line[1]) * 0.45)), None)
                if match is None:
                    lines.append([cy, item[4] - item[2], [item]])
                else:
                    match[2].append(item)
            blocks = []
            for _, _, line in lines:
                line.sort(key=lambda c: c[1])
                groups = [[]]
                for char in line:
                    group = groups[-1]
                    if group:
                        prev = group[-1]
                        height = max(prev[4] - prev[2], char[4] - char[2])
                        gap = char[1] - prev[3]
                        if gap > height * 2.0:
                            groups.append([])
                        elif gap > height * 0.28:
                            group.append((" ", prev[3], prev[2], char[1], prev[4]))
                    groups[-1].append(char)
                for group in groups:
                    x0 = min(c[1] for c in group)
                    y0 = min(c[2] for c in group)
                    x1 = max(c[3] for c in group)
                    y1 = max(c[4] for c in group)
                    blocks.append({"text": "".join(c[0] for c in group), "box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "confidence": 1.0, "source": "native_pdf"})
            blocks.sort(key=lambda block: (block["box"][0][1], block["box"][0][0]))
            # Une couche réduite à une seule ligne est trop peu probante.
            if len(lines) < 3:
                return None, "insufficient_coverage"
            return blocks, "native_pdf"
        finally:
            page.close()
    except Exception:
        return None, "pdf_analysis_error"
    finally:
        if document is not None:
            document.close()
