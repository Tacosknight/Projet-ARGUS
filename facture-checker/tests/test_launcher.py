"""Tests du lanceur avec configuration Uvicorn réelle sans flux console."""
import logging
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import launcher


class LauncherTests(unittest.TestCase):
    def test_real_uvicorn_configuration_and_log_with_no_console(self):
        root = logging.getLogger()
        old_handlers, old_level = root.handlers[:], root.level
        names = ("uvicorn", "uvicorn.error", "uvicorn.access", "paddle", "ppocr", "paddlex")
        previous = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
                    for name in names}
        with tempfile.TemporaryDirectory() as directory:
            try:
                # Ne pas fermer les handlers du runner lors de configure_logging.
                root.handlers = []
                with patch.object(launcher.app_paths, "LOG_DIR", Path(directory)), \
                        patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), \
                        patch.object(launcher, "os", SimpleNamespace(name="posix")):
                    log_path = launcher.configure_logging()
                    listener = Mock()
                    listener.getsockname.return_value = ("127.0.0.1", 8000)
                    server = launcher.create_server("127.0.0.1", listener)
                    server.config.load()
                    self.assertIsNone(server.config.log_config)
                    self.assertFalse(server.config.use_colors)
                    self.assertFalse(server.config.access_log)
                    launcher.report_error("Échec de recette", log_path)
                self.assertIn("Échec de recette", log_path.read_text(encoding="utf-8"))
            finally:
                for handler in root.handlers:
                    handler.close()
                root.handlers, root.level = old_handlers, old_level
                for name, (handlers, propagate) in previous.items():
                    logger = logging.getLogger(name)
                    logger.handlers, logger.propagate = handlers, propagate

    def test_port_error_reports_log_location_and_closes_socket(self):
        listener = Mock()
        listener.bind.side_effect = OSError("port occupied")
        with patch.object(sys, "argv", ["ARGUS", "--no-browser"]), \
                patch.object(launcher.app_paths, "ensure_app_directories"), \
                patch.object(launcher, "configure_logging", return_value=Path("argus.log")), \
                patch.object(launcher.socket, "socket", return_value=listener), \
                patch.object(launcher, "report_error") as report:
            launcher.main()
        report.assert_called_once()
        self.assertIn("8000", report.call_args.args[0])
        self.assertEqual(report.call_args.args[1], Path("argus.log"))
        listener.close.assert_called_once()

    def test_browser_is_not_opened_before_server_started(self):
        stopped = threading.Event()
        stopped.set()
        with patch.object(launcher.webbrowser, "open") as browser:
            launcher.open_when_ready(Mock(started=False), stopped, "http://127.0.0.1:8000")
        browser.assert_not_called()
