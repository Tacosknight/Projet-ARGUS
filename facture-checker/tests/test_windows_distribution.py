"""Tests isolés des garanties de la distribution Windows."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.ocr_engine import OCRInferenceError, OCRModelError, OCREngine
from core.ocr_models import validate_ocr_models


class OCRModelsTests(unittest.TestCase):
    def _model(self, root: Path, name: str, model_name: str) -> Path:
        path = root / name
        path.mkdir()
        (path / "inference.yml").write_text(
            f"Global:\n  model_name: {model_name}\n", encoding="utf-8"
        )
        (path / "inference.pdiparams").write_bytes(b"weights")
        (path / "inference.json").write_text("{}", encoding="utf-8")
        return path

    def test_safe_model_validation_returns_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._model(root, "text_detection", "PP-OCRv5_server_det")
            self._model(root, "text_recognition", "PP-OCRv5_server_rec")
            result = validate_ocr_models(root)
            self.assertTrue(result.is_valid)
            self.assertEqual(
                result.model_names,
                {
                    "text_detection": "PP-OCRv5_server_det",
                    "text_recognition": "PP-OCRv5_server_rec",
                },
            )

    def test_inference_failure_is_not_empty_result(self):
        import numpy as np

        engine = OCREngine()
        engine._ocr = Mock(
            predict=Mock(side_effect=RuntimeError("broken")),
            ocr=Mock(side_effect=RuntimeError("broken")),
        )
        with self.assertRaises(OCRInferenceError):
            engine.extract_text_and_boxes(np.zeros((2, 2, 3), dtype=np.uint8), use_cache=False)


class FrozenOCRTests(unittest.TestCase):
    def test_missing_models_fail_without_initializing_paddle(self):
        paddle = Mock()
        with tempfile.TemporaryDirectory() as directory, \
                patch("core.app_paths.MODELS_DIR", Path(directory)), \
                patch("core.app_paths.is_frozen", return_value=True), \
                patch.dict(sys.modules, {"paddleocr": types.SimpleNamespace(PaddleOCR=paddle)}):
            with self.assertRaisesRegex(OCRModelError, "modèles OCR locaux") as error:
                OCREngine()._get_ocr()
            self.assertIsNotNone(error.exception)
            paddle.assert_not_called()

    def test_invalid_models_never_fall_back_to_download(self):
        paddle = Mock(side_effect=ValueError("invalid model"))
        with tempfile.TemporaryDirectory() as directory:
            models = Path(directory)
            for name, model_name in (
                ("text_detection", "PP-OCRv5_server_det"),
                ("text_recognition", "PP-OCRv5_server_rec"),
            ):
                path = models / name
                path.mkdir()
                (path / "inference.yml").write_text(
                    f"Global:\n  model_name: {model_name}\n", encoding="utf-8"
                )
                (path / "inference.pdiparams").write_bytes(b"weights")
                (path / "inference.json").write_text("{}", encoding="utf-8")
            with patch("core.app_paths.MODELS_DIR", models), \
                    patch("core.app_paths.is_frozen", return_value=True), \
                    patch.dict(sys.modules, {"paddleocr": types.SimpleNamespace(PaddleOCR=paddle)}):
                with self.assertRaisesRegex(OCRModelError, "modèles OCR locaux") as error:
                    OCREngine()._get_ocr()
                self.assertIsInstance(error.exception.__cause__, ValueError)
            paddle.assert_called_once()
            self.assertEqual(paddle.call_args.kwargs["text_detection_model_dir"], str(models / "text_detection"))
            self.assertEqual(paddle.call_args.kwargs["text_recognition_model_dir"], str(models / "text_recognition"))


if __name__ == "__main__":
    unittest.main()
