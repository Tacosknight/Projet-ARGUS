"""Chemins applicatifs portables pour ARGUS.

Le code source et les binaires restent en lecture seule. Les factures, bases,
exports et journaux sont écrits dans le profil de l'utilisateur.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


APP_NAME = "ARGUS"
PACKAGE_DIR = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else PACKAGE_DIR


def data_dir() -> Path:
    override = os.environ.get("ARGUS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_NAME


DATA_DIR = data_dir()
DATABASE_PATH = DATA_DIR / "data" / "invoices.db"
OCR_CACHE_PATH = DATA_DIR / "data" / "ocr_cache.db"
INPUT_DIR = DATA_DIR / "imports"
EXPORT_DIR = DATA_DIR / "exports"
EXCEL_PATH = EXPORT_DIR / "factures_synthese.xlsx"
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = Path(os.environ.get("ARGUS_MODELS_DIR", resource_dir() / "models"))


def ensure_app_directories() -> None:
    for directory in (DATABASE_PATH.parent, INPUT_DIR, EXPORT_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    # Migration transparente depuis les anciennes versions qui écrivaient à
    # côté du code. Elle ne s'exécute qu'une fois, si la nouvelle cible est vide.
    for source, destination in (
        (PACKAGE_DIR / "invoices.db", DATABASE_PATH),
        (PACKAGE_DIR / "ocr_cache.db", OCR_CACHE_PATH),
        (PACKAGE_DIR / "factures_synthese.xlsx", EXCEL_PATH),
    ):
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)

    # Reprise non destructive des documents des versions sources précédentes.
    legacy_imports = PACKAGE_DIR / "input_photos"
    if legacy_imports.is_dir() and legacy_imports.resolve() != INPUT_DIR.resolve():
        for source in legacy_imports.rglob("*"):
            if source.is_file() and not source.is_symlink():
                destination = INPUT_DIR / source.relative_to(legacy_imports)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    continue
                # Le remplacement n'a lieu qu'après une copie complète.
                import tempfile
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                        temporary = Path(handle.name)
                    shutil.copy2(source, temporary)
                    os.replace(temporary, destination)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
