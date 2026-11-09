"""Point d'entrée graphique de la distribution Windows ARGUS."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import multiprocessing
import os
from pathlib import Path
import socket
import threading
import webbrowser

import uvicorn

from core import app_paths


LOGGER = logging.getLogger("ARGUS.launcher")
LOG_FILENAME = "argus.log"


def configure_logging() -> Path:
    """Configure le journal persistant et retourne son chemin.

    La configuration ne crée aucun ``StreamHandler`` : elle reste donc sûre
    pour un exécutable PyInstaller ``console=False`` où stdout/stderr peuvent
    être ``None``. Les journaux ne contiennent que le diagnostic technique,
    jamais le contenu des factures.
    """
    app_paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = app_paths.LOG_DIR / LOG_FILENAME
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "paddle", "ppocr", "paddlex"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
    return log_path


def report_error(message: str, log_path: Path | None = None) -> None:
    """Signale une erreur sans écrire dans stdout/stderr."""
    if log_path is not None:
        message = f"{message}\nJournal : {log_path}"
    LOGGER.error(message)
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "ARGUS — erreur de démarrage", 0x10)


def open_when_ready(
    server: uvicorn.Server,
    stopped: threading.Event,
    url: str,
    open_browser: bool = True,
) -> None:
    while not stopped.wait(0.1):
        if server.started:
            if open_browser:
                webbrowser.open(url)
            return


def create_server(host: str, listener: socket.socket) -> uvicorn.Server:
    """Construit un serveur Uvicorn sans gestionnaire lié à la console."""
    config = uvicorn.Config(
        "web.app:app",
        host=host,
        port=listener.getsockname()[1],
        reload=False,
        log_level="warning",
        log_config=None,
        access_log=False,
        use_colors=False,
    )
    return uvicorn.Server(config)


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mobile", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args, _ = parser.parse_known_args()
    listener = None
    stopped = threading.Event()
    log_path: Path | None = None
    try:
        app_paths.ensure_app_directories()
        log_path = configure_logging()
        LOGGER.info("Démarrage ARGUS (mode_mobile=%s)", args.mobile)
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        host = "0.0.0.0" if args.mobile else "127.0.0.1"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((host, 8000))
        listener.listen(2048)
        server = create_server(host, listener)
        threading.Thread(
            target=open_when_ready,
            args=(server, stopped, "http://127.0.0.1:8000", not args.no_browser),
            daemon=True,
        ).start()
        server.run(sockets=[listener])
        if not server.started:
            report_error("Le serveur ARGUS n'a pas pu démarrer.", log_path)
    except (Exception, SystemExit) as exc:
        report_error(
            f"Impossible de démarrer ARGUS : {exc}\nVérifiez notamment que le port 8000 est libre.",
            log_path,
        )
    finally:
        stopped.set()
        if listener is not None:
            listener.close()


if __name__ == "__main__":
    main()
