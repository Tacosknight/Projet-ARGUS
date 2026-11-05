"""
Module de cache déterministe pour les inférences PaddleOCR.
Stocke les résultats spatiaux (boîtes englobantes, textes et scores de confiance)
indexés par l'empreinte cryptographique SHA-256 de chaque image ou page analysée.
Permet d'obtenir des temps de réponse quasi-instantanés (<10ms) sur les pages récurrentes
ou les re-scans de factures multi-pages.
"""

from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("FactureChecker.OCRCache")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DB = BASE_DIR / "ocr_cache.db"


def compute_image_hash(image: Union[str, Path, bytes, np.ndarray]) -> str:
    """
    Calcule l'empreinte SHA-256 déterministe de l'image passée en paramètre.
    Supporte les chemins de fichiers, les octets bruts ou les matrices numpy.
    """
    hasher = hashlib.sha256()

    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier image introuvable pour le hachage : {image}")
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
    elif isinstance(image, bytes):
        hasher.update(image)
    elif isinstance(image, np.ndarray):
        hasher.update(image.tobytes())
        hasher.update(str(image.shape).encode("utf-8"))
    else:
        raise TypeError(f"Type non supporté pour le hachage de l'image : {type(image)}")

    return hasher.hexdigest()


class OCRResultCache:
    """
    Gestionnaire SQLite persistant pour la mise en cache des résultats OCR.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self.db_path = Path(db_path or DEFAULT_CACHE_DB)
        self._ensure_parent_dir()
        self.init_db()

    def _ensure_parent_dir(self) -> None:
        if self.db_path.parent and not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialise la table de cache OCR."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ocr_cache (
                    image_hash TEXT PRIMARY KEY,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    image_shape TEXT
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ocr_hash ON ocr_cache(image_hash);")
            conn.commit()

    def get(self, image: Union[str, Path, bytes, np.ndarray]) -> Optional[List[Dict[str, Any]]]:
        """
        Récupère les résultats OCR stockés pour une image donnée si présents en cache.
        """
        try:
            img_hash = compute_image_hash(image)
        except Exception as e:
            logger.debug("Impossible de calculer le hash pour le cache OCR : %s", e)
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT results_json FROM ocr_cache WHERE image_hash = ? LIMIT 1;",
                (img_hash,),
            )
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row["results_json"])
                    logger.debug("Cache OCR HIT pour le hash %s (%d éléments)", img_hash[:10], len(data))
                    return data
                except Exception as e:
                    logger.warning("Échec de désérialisation du cache OCR pour %s : %s", img_hash, e)
                    return None

        logger.debug("Cache OCR MISS pour le hash %s", img_hash[:10])
        return None

    def set(
        self,
        image: Union[str, Path, bytes, np.ndarray],
        results: List[Dict[str, Any]],
        image_shape: Optional[Tuple[int, ...]] = None,
    ) -> bool:
        """
        Enregistre les résultats OCR en cache pour une image.
        """
        try:
            img_hash = compute_image_hash(image)
            results_json = json.dumps(results, ensure_ascii=False)
            shape_str = str(image_shape) if image_shape else None
            now_iso = datetime.now().isoformat()

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO ocr_cache (image_hash, results_json, created_at, image_shape)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(image_hash) DO UPDATE SET
                        results_json = excluded.results_json,
                        created_at = excluded.created_at,
                        image_shape = excluded.image_shape;
                    """,
                    (img_hash, results_json, now_iso, shape_str),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.warning("Échec de mise en cache OCR : %s", e)
            return False

    def clear(self) -> int:
        """Vide le cache complet et retourne le nombre d'entrées supprimées."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ocr_cache;")
            count = cursor.rowcount
            conn.commit()
            return count

    def size(self) -> int:
        """Retourne le nombre d'entrées en cache."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM ocr_cache;")
            row = cursor.fetchone()
            return row["cnt"] if row else 0


# Instance globale partagée
_DEFAULT_CACHE: Optional[OCRResultCache] = None


def get_ocr_cache() -> OCRResultCache:
    """Retourne l'instance singleton du cache OCR."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        _DEFAULT_CACHE = OCRResultCache()
    return _DEFAULT_CACHE
