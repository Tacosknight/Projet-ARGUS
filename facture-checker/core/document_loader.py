"""Chargement commun des images et PDF multipages."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Tuple

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


def iter_document_pages(path: Path, pdf_scale: float = 2.0) -> Iterator[Tuple[int, int, np.ndarray]]:
    """Produit ``(numéro, total, image BGR)`` pour une image ou chaque page PDF."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            raise RuntimeError("Le composant PDF pypdfium2 n'est pas installé.") from exc

        document = pdfium.PdfDocument(str(path))
        total = len(document)
        try:
            for index in range(total):
                page = document[index]
                bitmap = page.render(scale=pdf_scale)
                pil_image = bitmap.to_pil()
                rgb = np.asarray(pil_image.convert("RGB"))
                yield index + 1, total, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        finally:
            document.close()
        return

    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError(f"Format de document non pris en charge : {suffix or 'sans extension'}")
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Impossible de décoder l'image : {path.name}")
    yield 1, 1, image
