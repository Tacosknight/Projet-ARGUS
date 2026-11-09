"""Copie récupérable des fichiers d'une sauvegarde (hors export régénérable)."""

from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import json
import shutil
import sqlite3
import tempfile
import zipfile


class RecoveryError(OSError):
    """Une récupération nécessite une intervention ; ne pas supprimer le staging."""


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def snapshot_sqlite(source: Path, destination: Path) -> None:
    """Utilise l'API SQLite pour inclure aussi un éventuel journal WAL."""
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(destination)) as copy:
        original.backup(copy)


def extract_backup(archive_path: Path, content: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if "data/invoices.db" not in {item.filename for item in members}:
            raise ValueError("La base invoices.db est absente de la sauvegarde.")
        # Refuser les chemins Windows aussi sur Linux ; pas de chemins ambigus.
        names = set()
        total = 0
        for item in members:
            name = item.filename
            path = PurePosixPath(name)
            if ("\\" in name or PureWindowsPath(name).drive or path.is_absolute()
                    or ".." in path.parts or ":" in name
                    or not path.parts or path.parts[0] not in {"data", "imports", "exports"}):
                raise ValueError("Chemin interdit dans la sauvegarde.")
            key = name.rstrip("/").casefold()
            if key in names:
                raise ValueError("Chemin dupliqué dans la sauvegarde.")
            names.add(key)
            total += item.file_size
            if total > 4 * 1024 ** 3 or len(members) > 20000:
                raise ValueError("Sauvegarde trop volumineuse.")
        archive.extractall(content)
    candidate = content / "data" / "invoices.db"
    with closing(sqlite3.connect(candidate)) as connection:
        result = connection.execute("PRAGMA integrity_check;").fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(invoices)")}
        if not result or result[0] != "ok" or not {"id", "filename", "status", "unique_hash"}.issubset(columns):
            raise ValueError("La base sauvegardée n'est pas une base ARGUS valide.")
    cache = content / "data" / "ocr_cache.db"
    if cache.is_file():
        with closing(sqlite3.connect(cache)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(ocr_cache)")}
            if (connection.execute("PRAGMA integrity_check;").fetchone() != ("ok",)
                    or not {"image_hash", "results_json", "created_at", "image_shape"}.issubset(columns)):
                raise ValueError("Le cache sauvegardé est endommagé ou incompatible.")
    return candidate


def apply_restore(content: Path, database: Path, cache: Path, imports: Path, recovery: Path) -> None:
    """Appeler sous DATA_LOCK, connexions fermées. Annule les copies sur erreur E/S.

    Les imports absents de l'archive sont conservés (restauration par fusion).
    Les fichiers de récupération restent sur disque si l'annulation échoue.
    """
    changes = [(content / "data" / "invoices.db", database)]
    candidate_cache = content / "data" / "ocr_cache.db"
    # Un cache absent ne doit pas conserver les inférences d'une autre sauvegarde.
    changes.append((candidate_cache if candidate_cache.is_file() else None, cache))
    source_imports = content / "imports"
    if source_imports.is_dir():
        changes.extend((source, imports / source.relative_to(source_imports))
                       for source in sorted(source_imports.rglob("*")) if source.is_file())
    recovery.mkdir(parents=True)
    previous = []
    for index, (_, target) in enumerate(changes):
        saved = recovery / str(index) if target.exists() else None
        if saved is not None:
            shutil.copy2(target, saved)
        previous.append(saved)
    # Documenter les cibles : les copies seules ne suffisent pas si le rollback
    # échoue et qu'une récupération manuelle est nécessaire.
    (recovery / "manifest.json").write_text(json.dumps([
        {"target": str(target), "previous": str(saved) if saved is not None else None}
        for (_, target), saved in zip(changes, previous)
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    applied = []
    try:
        for (source, target), saved in zip(changes, previous):
            if source is None:
                target.unlink(missing_ok=True)
            else:
                atomic_copy(source, target)
            applied.append((target, saved))
    except OSError as exc:
        failures = []
        for target, saved in reversed(applied):
            try:
                if saved is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_copy(saved, target)
            except OSError:
                failures.append(str(target))
        if failures:
            raise RecoveryError(
                f"Récupération incomplète. Conservez {recovery.parent} et contactez le support."
            ) from exc
        raise
