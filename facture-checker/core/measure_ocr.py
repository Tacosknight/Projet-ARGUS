"""Mesure locale sans contenu sensible : python -m core.measure_ocr fichier [fichier ...].

Trois passages : moteur neuf sans cache, même moteur sans cache, puis cache
isolé prérempli. La première inférence seule mesure le démarrage à froid ;
les pages natives n'initialisent pas le moteur. Aucun résultat OCR n'est affiché.
Le cache temporaire contient du texte sensible et est supprimé à la fin.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import logging
import os
from pathlib import Path
import tempfile
import time

from core.document_loader import iter_document_pages
from core.ocr_engine import OCREngine
from core.ocr_cache import OCRResultCache
import core.ocr_cache as cache_module
from core.parser import parse_invoice
from core.pdf_native import native_pdf_page
from core.preprocessor import preprocess_image

CRITICAL_FIELDS = ("numero_facture", "date_facture", "montant_ht", "montant_ttc", "serial_numbers")


def measure(paths, profile="web"):
    """Retourne des métriques anonymes, sans noms de fichiers ni valeurs extraites."""
    engine = OCREngine()
    old_cache = cache_module._DEFAULT_CACHE
    records = []
    try:
        with tempfile.TemporaryDirectory(prefix="argus-ocr-measure-") as tmp:
            cache_module._DEFAULT_CACHE = OCRResultCache(Path(tmp) / "cache.sqlite")
            # Le passage chaud alimente aussi le cache ; les mêmes pixels sont réutilisés.
            for mode in ("cold", "warm", "cache"):
                for document_index, path in enumerate(paths, 1):
                    path = Path(path)
                    pages = iter(iter_document_pages(path))
                    while True:
                        start = time.perf_counter()
                        try:
                            number, total, image = next(pages)
                        except StopIteration:
                            break
                        render = time.perf_counter() - start
                        record = {"mode": mode, "document": document_index, "page": number,
                                  "pages": total, "render_seconds": render}
                        blocks = None
                        if path.suffix.lower() == ".pdf":
                            start = time.perf_counter()
                            blocks, reason = native_pdf_page(path, number)
                            record.update(native_seconds=time.perf_counter() - start, native_reason=reason)
                        if blocks:
                            record.update(source="native_pdf", cache="not_applicable")
                        else:
                            record["source"] = "ocr"
                            start = time.perf_counter()
                            height, threshold = (2400, False) if profile == "web" else (1600, True)
                            prepared = preprocess_image(image, target_height=height, apply_threshold=threshold)
                            record["preprocess_seconds"] = time.perf_counter() - start
                            start = time.perf_counter()
                            metrics = {}
                            blocks = engine.extract_text_and_boxes(prepared, use_cache=mode == "cache", metrics=metrics)
                            record["ocr_seconds"] = time.perf_counter() - start
                            record.update(metrics)
                            if mode == "warm" and blocks:
                                start = time.perf_counter()
                                cache_module._DEFAULT_CACHE.set(prepared, blocks, image_shape=prepared.shape)
                                record["cache_seed_seconds"] = time.perf_counter() - start
                        record["blocks"] = len(blocks)
                        start = time.perf_counter()
                        parsed = parse_invoice(blocks) if blocks else {}
                        record["parse_seconds"] = time.perf_counter() - start
                        record["missing_fields"] = [name for name in CRITICAL_FIELDS if not parsed.get(name)]
                        records.append(record)
    finally:
        cache_module._DEFAULT_CACHE = old_cache
    return {"profile": profile, "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--profile", choices=("web", "cli"), default="web")
    args = parser.parse_args()
    # Les bibliothèques peuvent journaliser des chemins ou du texte : silence par défaut.
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = measure(args.files, args.profile)
    except Exception:
        parser.exit(1, "Mesure impossible ; vérifier les fichiers et dépendances localement.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
