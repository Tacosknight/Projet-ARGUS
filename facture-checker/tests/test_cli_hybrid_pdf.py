import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import main


NATIVE = [{"text": "Texte natif", "box": [[0, 0], [10, 0], [10, 10], [0, 10]], "confidence": 1.0}]
OCR = [{"text": "Texte OCR", "box": [[0, 0], [10, 0], [10, 10], [0, 10]], "confidence": 0.9}]


@pytest.fixture
def pipeline():
    db = Mock()
    db.get_all_invoices.return_value = []
    validator = Mock()
    validator.validate.return_value = ("VALIDE", [], "hash")
    engine = Mock()
    engine.extract_text_and_boxes.return_value = OCR
    return db, validator, engine


def test_native_pdf_skips_preprocessing_and_ocr(pipeline, tmp_path):
    db, validator, engine = pipeline
    native = Mock(return_value=(NATIVE, "accepted"))
    pdf = tmp_path / "invoice.pdf"
    with patch.dict(sys.modules, {"core.pdf_native": types.SimpleNamespace(native_pdf_page=native)}), \
         patch.object(main, "preprocess_image") as preprocess, \
         patch.object(main, "parse_invoice", return_value={}) as parse:
        result = main.process_single_image(tmp_path / "page.jpg", engine, validator, db,
                                           forced_type="CLIENT", page_current=2, page_total=3,
                                           pdf_source_path=pdf)
    native.assert_called_once_with(pdf, 2)
    preprocess.assert_not_called()
    engine.extract_text_and_boxes.assert_not_called()
    parse.assert_called_once_with(NATIVE, forced_type="CLIENT")
    assert (result["page_current"], result["page_total"]) == (2, 3)
    db.save_invoice.assert_called_once()


@pytest.mark.parametrize("outcome", [(None, "scan"), ([], "empty"), RuntimeError("secret")])
def test_rejected_or_failed_native_falls_back_to_ocr(pipeline, tmp_path, outcome, caplog):
    db, validator, engine = pipeline
    native = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    with patch.dict(sys.modules, {"core.pdf_native": types.SimpleNamespace(native_pdf_page=native)}), \
         patch.object(main, "preprocess_image", return_value="pixels") as preprocess, \
         patch.object(main, "parse_invoice", return_value={}) as parse:
        result = main.process_single_image(tmp_path / "page.jpg", engine, validator, db,
                                           pdf_source_path=tmp_path / "invoice.pdf")
    preprocess.assert_called_once_with(tmp_path / "page.jpg", target_height=1600, apply_threshold=True)
    engine.extract_text_and_boxes.assert_called_once_with("pixels")
    parse.assert_called_once_with(OCR, forced_type=None)
    assert result["status"] == "VALIDE"
    assert "secret" not in caplog.text


def test_image_still_uses_ocr_and_empty_result_is_saved(pipeline, tmp_path):
    db, validator, engine = pipeline
    engine.extract_text_and_boxes.return_value = []
    native = Mock()
    with patch.dict(sys.modules, {"core.pdf_native": types.SimpleNamespace(native_pdf_page=native)}), \
         patch.object(main, "preprocess_image", return_value="pixels"):
        result = main.process_single_image(tmp_path / "image.png", engine, validator, db)
    native.assert_not_called()
    engine.extract_text_and_boxes.assert_called_once_with("pixels")
    assert result["status"] == "A_VERIFIER"
    assert "Aucun texte lisible" in result["error_details"][0]
    db.save_invoice.assert_called_once_with(result)


def test_batch_mixed_pages_uses_original_pdf_and_consolidates(pipeline, tmp_path):
    import numpy as np

    db, validator, engine = pipeline
    pdf = tmp_path / "invoice.pdf"
    pdf.touch()
    native = Mock(side_effect=[(NATIVE, "accepted"), (None, "scan")])
    pages = [(1, 2, np.zeros((10, 10, 3), dtype=np.uint8)),
             (2, 2, np.zeros((10, 10, 3), dtype=np.uint8))]
    saved = []
    db.save_invoice.side_effect = lambda record: saved.append(record.copy())
    db.get_all_invoices.side_effect = lambda: saved[:]
    with patch.dict(sys.modules, {"core.pdf_native": types.SimpleNamespace(native_pdf_page=native)}), \
         patch.object(main, "InvoiceDatabase", return_value=db), \
         patch.object(main, "InvoiceValidator", return_value=validator), \
         patch.object(main, "OCREngine", return_value=engine), \
         patch.object(main, "iter_document_pages", return_value=iter(pages)), \
         patch.object(main, "preprocess_image", return_value="pixels") as preprocess, \
         patch.object(main, "parse_invoice", return_value={}) as parse, \
         patch.object(main, "are_pages_of_same_invoice", return_value=True), \
         patch.object(main, "consolidate_pages", side_effect=lambda records: {**records[-1], "is_multipage": True}) as consolidate, \
         patch.object(main, "export_to_excel", return_value=tmp_path / "out.xlsx"), \
         patch.object(main, "reconcile_invoices", return_value={"items": [], "kpi": {"total_serials_detected": 0, "rapproches_count": 0, "non_refactures_count": 0, "volume_dépenses_orphelines": 0, "taux_couverture": 0}}):
        main.run_batch_processing(tmp_path, tmp_path / "db.sqlite", tmp_path / "out.xlsx")
    assert [call.args for call in native.call_args_list] == [(pdf, 1), (pdf, 2)]
    assert [call.args[0] for call in parse.call_args_list] == [NATIVE, OCR]
    assert preprocess.call_count == engine.extract_text_and_boxes.call_count == 1
    assert consolidate.call_count == 1
    assert saved[-1]["is_multipage"]
    assert not Path(saved[0]["filename"]).is_absolute()
    assert pdf.exists()
