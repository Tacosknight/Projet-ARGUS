"""Régressions E/S Windows simulées ; aucun modèle OCR téléchargé."""
import io
from contextlib import ExitStack
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

import numpy as np
from fastapi.testclient import TestClient
import web.app as web_app
from core.validator import InvoiceValidator
from storage.database import InvoiceDatabase
from storage.export_excel import export_to_excel
from storage.backup import apply_restore, atomic_copy, RecoveryError


class ExcelAtomicTests(unittest.TestCase):
    def test_old_workbook_survives_save_or_replace_error(self):
        for target in ("openpyxl.Workbook.save", "storage.export_excel.os.replace"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "export.xlsx"
                path.write_bytes(b"previous")
                with patch(target, side_effect=PermissionError("locked")):
                    with self.assertRaises(PermissionError):
                        export_to_excel([], path)
                self.assertEqual(path.read_bytes(), b"previous")
                self.assertEqual(list(Path(directory).iterdir()), [path])
                export_to_excel([], path)
                self.assertTrue(zipfile.is_zipfile(path))


class APIReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = InvoiceDatabase(str(self.root / "data" / "invoices.db"))
        self.imports = self.root / "imports"
        self.imports.mkdir()
        self.stack = ExitStack()
        for name, value in {"db": self.database, "DB_PATH": Path(self.database.db_path),
                            "DATA_DIR": self.root, "INPUT_DIR": self.imports,
                            "EXCEL_PATH": self.root / "export.xlsx",
                            "validator": InvoiceValidator(db_is_duplicate_fn=self.database.is_hash_exists)}.items():
            self.stack.enter_context(patch.object(web_app, name, value))
        self.client = TestClient(web_app.app)
        self.identifier = self.database.save_invoice({"filename": "source.jpg", "unique_hash": "old", "status": "A_VERIFIER"})

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_excel_lock_does_not_turn_committed_operations_into_failure(self):
        with patch.object(web_app, "export_to_excel", side_effect=PermissionError("locked")):
            response = self.client.put(f"/api/invoices/{self.identifier}", json={"numero_facture": "changed"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["warnings"])
            self.assertEqual(self.database.get_invoice_by_id(self.identifier)["numero_facture"], "changed")
            self.assertEqual(self.client.get("/api/export").status_code, 503)
            response = self.client.delete(f"/api/invoices/{self.identifier}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["warnings"])
            self.assertIsNone(self.database.get_invoice_by_id(self.identifier))
            self.database.save_invoice({"filename": "again.jpg", "unique_hash": "again", "status": "A_VERIFIER"})
            response = self.client.delete("/api/invoices")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["warnings"])
            self.assertEqual(self.database.get_all_invoices(), [])

    def test_scan_ocr_failure_is_technical_and_does_not_insert(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        with patch.object(web_app, "iter_document_pages", return_value=[(1, 1, image)]), \
                patch.object(web_app, "preprocess_image", return_value=image), \
                patch.object(web_app.ocr_engine, "extract_text_and_boxes", side_effect=RuntimeError("OCR indisponible")):
            response = self.client.post("/api/scan", files={"file": ("scan.jpg", b"image", "image/jpeg")})
        self.assertEqual(response.status_code, 503)
        self.assertIn("OCR indisponible", response.json()["detail"])
        self.assertEqual(len(self.database.get_all_invoices()), 1)

    def test_blank_scan_keeps_no_text_diagnostic_and_export_warning(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        with patch.object(web_app, "iter_document_pages", return_value=[(1, 1, image)]), \
                patch.object(web_app, "preprocess_image", return_value=image), \
                patch.object(web_app.ocr_engine, "extract_text_and_boxes", return_value=[]), \
                patch.object(web_app, "export_to_excel", side_effect=PermissionError()):
            response = self.client.post("/api/scan", files={"file": ("scan.jpg", b"image", "image/jpeg")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["warnings"])
        self.assertIn("Aucun texte lisible détecté sur cette page.", response.json()["error_details"])

    def test_pdf_page_is_written_to_accented_directory(self):
        accented = self.imports / "Noémie été"
        accented.mkdir()
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        with patch.object(web_app, "INPUT_DIR", accented), \
                patch.object(web_app, "iter_document_pages", return_value=[(1, 1, image)]), \
                patch.object(web_app, "preprocess_image", return_value=image), \
                patch.object(web_app.ocr_engine, "extract_text_and_boxes", return_value=[]):
            response = self.client.post("/api/scan", files={"file": ("été.pdf", b"pdf", "application/pdf")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue((accented / response.json()["filename"]).is_file())

    def test_diagnostics_reject_empty_model_directories_without_loading_ocr(self):
        models = self.root / "models"
        (models / "text_detection").mkdir(parents=True)
        (models / "text_recognition").mkdir()
        with patch.object(web_app, "MODELS_DIR", models), \
                patch.object(web_app.ocr_engine, "_get_ocr") as load:
            response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200)
        check = next(item for item in response.json()["checks"] if item["name"] == "Modèles OCR hors ligne")
        self.assertFalse(check["ok"])
        load.assert_not_called()

    def test_successful_export_download_is_valid_and_snapshot_is_removed(self):
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(response.content)))
        self.assertEqual(list(self.root.glob("*.xlsx")), [self.root / "export.xlsx"])

    def test_document_error_keeps_http_400(self):
        with patch.object(web_app, "iter_document_pages", side_effect=ValueError("format invalide")):
            response = self.client.post("/api/scan", files={"file": ("bad.pdf", b"bad", "application/pdf")})
        self.assertEqual(response.status_code, 400)

    def backup_bytes(self):
        (self.imports / "source.jpg").write_bytes(b"document")
        response = self.client.get("/api/backup")
        self.assertEqual(response.status_code, 200)
        return response.content

    def test_restore_regenerates_excel_and_succeeds_despite_excel_lock(self):
        archive = self.backup_bytes()
        self.database.update_invoice(self.identifier, {"numero_facture": "later"})
        with patch.object(web_app, "export_to_excel", side_effect=PermissionError()):
            response = self.client.post("/api/restore", files={"file": ("backup.zip", archive, "application/zip")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["warnings"])
        self.assertIsNone(self.database.get_invoice_by_id(self.identifier)["numero_facture"])
        self.assertEqual((self.imports / "source.jpg").read_bytes(), b"document")

    def test_restore_rejects_windows_traversal_without_change(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("data/invoices.db", b"bad")
            archive.writestr("imports/..\\outside", b"bad")
        response = self.client.post("/api/restore", files={"file": ("backup.zip", buffer.getvalue(), "application/zip")})
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(self.database.get_invoice_by_id(self.identifier))


class RestoreRecoveryTests(unittest.TestCase):
    def prepare(self, root):
        content = root / "content"
        (content / "data").mkdir(parents=True)
        (content / "imports").mkdir()
        database = root / "db"
        cache = root / "cache"
        imports = root / "imports"
        imports.mkdir()
        for target, value in ((database, b"old-db"), (cache, b"old-cache"),
                              (imports / "z", b"old-import"),
                              (content / "data" / "invoices.db", b"new-db"),
                              (content / "data" / "ocr_cache.db", b"new-cache"),
                              (content / "imports" / "a", b"new-file"),
                              (content / "imports" / "z", b"new-import")):
            target.write_bytes(value)
        return content, database, cache, imports, root / "recovery"

    def test_every_apply_failure_rolls_back_database_cache_and_imports(self):
        for fail_at in (2, 3, 4):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as directory:
                arguments = self.prepare(Path(directory))
                calls = 0
                def fail_once(source, target):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise PermissionError("injected")
                    return atomic_copy(source, target)
                with patch("storage.backup.atomic_copy", side_effect=fail_once):
                    with self.assertRaises(PermissionError):
                        apply_restore(*arguments)
                _, database, cache, imports, _ = arguments
                self.assertEqual(database.read_bytes(), b"old-db")
                self.assertEqual(cache.read_bytes(), b"old-cache")
                self.assertEqual((imports / "z").read_bytes(), b"old-import")
                self.assertFalse((imports / "a").exists())

    def test_failed_rollback_keeps_recovery_files(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = self.prepare(Path(directory))
            calls = 0
            def fail(source, target):
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise PermissionError("injected")
                return atomic_copy(source, target)
            with patch("storage.backup.atomic_copy", side_effect=fail):
                with self.assertRaises(RecoveryError):
                    apply_restore(*arguments)
            self.assertTrue((arguments[-1] / "0").is_file())


class MigrationTests(unittest.TestCase):
    def test_import_migration_is_non_destructive_and_repeatable(self):
        import core.app_paths as paths
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            package = root / "old"
            (package / "input_photos" / "sub").mkdir(parents=True)
            (package / "input_photos" / "sub" / "a.jpg").write_bytes(b"original")
            for name, value in {"PACKAGE_DIR": package, "INPUT_DIR": root / "imports",
                                "DATABASE_PATH": root / "data" / "invoices.db",
                                "OCR_CACHE_PATH": root / "data" / "cache.db",
                                "EXPORT_DIR": root / "exports", "EXCEL_PATH": root / "exports" / "export.xlsx",
                                "LOG_DIR": root / "logs"}.items():
                stack.enter_context(patch.object(paths, name, value))
            paths.ensure_app_directories()
            migrated = root / "imports" / "sub" / "a.jpg"
            self.assertEqual(migrated.read_bytes(), b"original")
            migrated.write_bytes(b"newer")
            paths.ensure_app_directories()
            self.assertEqual(migrated.read_bytes(), b"newer")
            self.assertTrue((package / "input_photos" / "sub" / "a.jpg").exists())
