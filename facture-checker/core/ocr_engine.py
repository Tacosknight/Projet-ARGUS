"""
Module OCR basé sur PaddleOCR.
Fournit la détection et la reconnaissance de texte ainsi que les coordonnées spatiales
des boîtes englobantes (bounding boxes).
Compatible avec PaddleOCR v2.x et v3.x.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import logging
import cv2
import numpy as np

# Configuration du logger
logger = logging.getLogger("FactureChecker.OCR")


class OCREngine:
    """
    Wrapper modulaire autour de PaddleOCR avec gestion paresseuse (lazy loading)
    et normalisation structurée des boîtes englobantes spatiales.
    """

    def __init__(
        self,
        lang: str = "fr",
        use_angle_cls: bool = True,
        show_log: bool = False,
    ) -> None:
        """
        Initialise le moteur OCR.

        Args:
            lang (str): Langue de reconnaissance (défaut 'fr').
            use_angle_cls (bool): Active le classificateur d'orientation (rotation).
            show_log (bool): Affiche les logs internes de PaddleOCR.
        """
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.show_log = show_log
        self._ocr: Optional[Any] = None

    def _get_ocr(self) -> Any:
        """
        Charge et retourne l'instance du modèle PaddleOCR de manière paresseuse.
        """
        if self._ocr is None:
            from paddleocr import PaddleOCR

            # Suppression des logs verbeux
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            logging.getLogger("paddlex").setLevel(logging.ERROR)

            logger.info(
                "Initialisation du modèle PaddleOCR (lang=%s, use_angle_cls=%s)...",
                self.lang,
                self.use_angle_cls,
            )
            # Gestion de la compatibilité des arguments selon la version de PaddleOCR
            try:
                # PaddleOCR v3 / PaddleX
                self._ocr = PaddleOCR(lang=self.lang)
            except Exception:
                try:
                    self._ocr = PaddleOCR(use_angle_cls=self.use_angle_cls, lang=self.lang)
                except Exception:
                    self._ocr = PaddleOCR()

        return self._ocr

    def extract_text_and_boxes(
        self, image: Union[str, Path, np.ndarray]
    ) -> List[Dict[str, Any]]:
        """
        Exécute la détection et reconnaissance de texte sur l'image donnée.

        Args:
            image (Union[str, Path, np.ndarray]): Image BGR en mémoire ou chemin vers le fichier.

        Returns:
            List[Dict[str, Any]]: Liste d'éléments détectés :
                [
                    {
                        "text": str,
                        "box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
                        "confidence": float
                    },
                    ...
                ]
        """
        # Chargement de l'image si un chemin est passé
        if isinstance(image, (str, Path)):
            img_path = str(image)
            data = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"Impossible de lire l'image à partir du chemin : {img_path}")
        elif isinstance(image, np.ndarray):
            img = image
        else:
            raise TypeError(f"Type d'image non supporté : {type(image)}")

        if img.size == 0:
            return []

        ocr_instance = self._get_ocr()

        try:
            # Exécution de PaddleOCR (compatible v2.x et v3.x / PaddleX)
            if hasattr(ocr_instance, "predict"):
                raw_results = ocr_instance.predict(img)
            else:
                raw_results = ocr_instance.ocr(img)
        except Exception as e:
            try:
                raw_results = ocr_instance.ocr(img)
            except Exception as e2:
                logger.error("Erreur durant l'exécution de PaddleOCR : %s", e2)
                raise RuntimeError(f"Échec de l'inférence OCR : {e2}") from e2

        # Gestion des résultats vides
        if not raw_results:
            return []

        formatted_lines: List[Dict[str, Any]] = []

        first_item = raw_results[0]
        if first_item is None:
            return []

        # Cas 1 : PaddleOCR v3.x / PaddleX (dictionnaire avec rec_texts, rec_polys/dt_polys, rec_scores)
        if isinstance(first_item, dict):
            rec_texts = first_item.get("rec_texts", [])
            rec_polys = first_item.get("rec_polys") or first_item.get("dt_polys") or []
            rec_scores = first_item.get("rec_scores", [])

            for i, text in enumerate(rec_texts):
                text_str = str(text).strip()
                score = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                poly = rec_polys[i] if i < len(rec_polys) else []

                if hasattr(poly, "tolist"):
                    poly_list = poly.tolist()
                elif isinstance(poly, (list, tuple)):
                    poly_list = list(poly)
                else:
                    poly_list = []

                box = [[float(pt[0]), float(pt[1])] for pt in poly_list] if poly_list else []

                formatted_lines.append(
                    {
                        "text": text_str,
                        "box": box,
                        "confidence": round(score, 4),
                    }
                )

        # Cas 2 : Format classique PaddleOCR v2.x ([[box, (text, score)], ...])
        elif isinstance(first_item, list):
            for item in first_item:
                if not item or len(item) < 2:
                    continue

                raw_box = item[0]
                raw_text_info = item[1]

                box = [[float(pt[0]), float(pt[1])] for pt in raw_box]
                text = str(raw_text_info[0]).strip()
                confidence = float(raw_text_info[1]) if len(raw_text_info) > 1 else 0.0

                formatted_lines.append(
                    {
                        "text": text,
                        "box": box,
                        "confidence": round(confidence, 4),
                    }
                )

        return formatted_lines


# Instance singleton globale pour réutilisation
_DEFAULT_ENGINE: Optional[OCREngine] = None


def extract_text_and_boxes(
    image: Union[str, Path, np.ndarray],
    lang: str = "fr",
    use_angle_cls: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fonction utilitaire directe pour extraire textes et boîtes spatiales
    sans instancier manuellement OCREngine.
    """
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None or _DEFAULT_ENGINE.lang != lang:
        _DEFAULT_ENGINE = OCREngine(lang=lang, use_angle_cls=use_angle_cls)
    return _DEFAULT_ENGINE.extract_text_and_boxes(image)
