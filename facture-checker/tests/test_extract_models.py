"""Tests de l'extraction contrôlée des archives de modèles de release."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[2] / "packaging" / "extract_models.py"
spec = importlib.util.spec_from_file_location("argus_extract_models", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ModelArchiveTests(unittest.TestCase):
    def extract(self, entries):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "models.zip"
            destination = root / "out"
            destination.mkdir()
            with zipfile.ZipFile(archive, "w") as output:
                for name, contents in entries:
                    output.writestr(name, contents)
            module.extract(archive, destination)
            return {str(path.relative_to(destination)).replace("\\", "/"): path.read_bytes()
                    for path in destination.rglob("*") if path.is_file()}

    def test_accepts_root_or_models_prefix(self):
        for prefix in ("", "models/"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    self.extract([(prefix + "text_detection/inference.yml", "test")]),
                    {"text_detection/inference.yml": b"test"},
                )

    def test_rejects_duplicate_normalized_paths(self):
        with self.assertRaisesRegex(ValueError, "dupliqué"):
            self.extract([("text_detection/inference.yml", "a"),
                          ("models/text_detection/inference.yml", "b")])

    def test_rejects_unexpected_paths(self):
        for name in ("models/../text_detection/inference.yml", "models/text_detection/script.py",
                     "/models/text_detection/inference.yml", "models\\text_detection/inference.yml"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract([(name, "bad")])


if __name__ == "__main__":
    unittest.main()
