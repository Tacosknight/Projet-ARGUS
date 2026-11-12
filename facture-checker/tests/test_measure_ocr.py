import json
from unittest.mock import Mock

import numpy as np

from core import measure_ocr
from core.ocr_engine import OCREngine


def test_engine_metrics_cache_and_no_content(monkeypatch):
    image = np.ones((2, 2, 3), dtype=np.uint8)
    secret = "Patient SECRET 123456"
    blocks = [{"text": secret, "box": [], "confidence": 0.9}]
    cache = Mock()
    cache.get.side_effect = [None, blocks]
    monkeypatch.setattr("core.ocr_cache.get_ocr_cache", lambda: cache)
    engine = OCREngine()
    monkeypatch.setattr(engine, "_get_ocr", lambda: Mock(predict=lambda image: [[ [[], (secret, 0.9)] ]]))
    first, second = {}, {}
    assert engine.extract_text_and_boxes(image, metrics=first) == blocks
    assert engine.extract_text_and_boxes(image, metrics=second) == blocks
    assert first["cache"] == "miss" and first["blocks"] == 1
    assert second["cache"] == "hit" and second["blocks"] == 1
    assert secret not in json.dumps([first, second])


def test_measure_native_and_ocr_anonymous(monkeypatch, tmp_path):
    image = np.ones((2, 2, 3), dtype=np.uint8)
    monkeypatch.setattr(measure_ocr, "iter_document_pages", lambda p: iter([(1, 2, image), (2, 2, image)]))
    secret = "SECRET patient 123"
    block = {"text": secret, "box": [], "confidence": 1}
    monkeypatch.setattr(measure_ocr, "native_pdf_page", lambda p, n: ([block], "native_pdf") if n == 1 else (None, "image_present"))
    monkeypatch.setattr(measure_ocr, "preprocess_image", lambda image, **kw: image)
    monkeypatch.setattr(measure_ocr, "parse_invoice", lambda blocks: {"numero_facture": secret})
    class Engine:
        def extract_text_and_boxes(self, image, use_cache, metrics):
            metrics.update(cache="miss" if use_cache else "disabled", blocks=1)
            return [block]
    monkeypatch.setattr(measure_ocr, "OCREngine", Engine)
    result = measure_ocr.measure([tmp_path / "SECRET.pdf"])
    assert len(result["records"]) == 6
    assert [r["source"] for r in result["records"][:2]] == ["native_pdf", "ocr"]
    assert "numero_facture" not in result["records"][0]["missing_fields"]
    assert secret not in json.dumps(result)
    assert "SECRET.pdf" not in json.dumps(result)
