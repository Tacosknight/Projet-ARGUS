"""Validation statique des modèles OCR locaux ARGUS.

Ce module ne charge jamais PaddleOCR. Il lit uniquement ``inference.yml`` avec
PyYAML ``safe_load`` et vérifie les fichiers attendus par PaddleX. Le diagnostic
peut donc l'utiliser sans déclencher un téléchargement ou une inférence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml


ModelPath = Union[str, Path]


@dataclass(frozen=True)
class OCRModelInfo:
    """Description d'un modèle dont les fichiers locaux ont été inspectés."""

    role: str
    path: Path
    model_name: Optional[str]
    files_present: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class OCRModelValidation:
    """Résultat de la validation des fichiers, sans chargement du modèle."""

    root: Path
    detection: OCRModelInfo
    recognition: OCRModelInfo
    orientation: Optional[OCRModelInfo]
    require_orientation: bool = False

    @property
    def errors(self) -> tuple[str, ...]:
        values = [self.detection, self.recognition]
        if self.orientation is not None:
            values.append(self.orientation)
        errors = [item.error for item in values if item.error]
        if self.require_orientation and self.orientation is None:
            errors.append("modèle d'orientation absent")
        return tuple(errors)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def model_names(self) -> dict[str, str]:
        """Retourne les noms PaddleX vérifiés, indexés par rôle."""
        values = {
            "text_detection": self.detection,
            "text_recognition": self.recognition,
        }
        if self.orientation is not None:
            values["textline_orientation"] = self.orientation
        return {
            role: info.model_name
            for role, info in values.items()
            if info.model_name is not None
        }

    def error_message(self) -> str:
        if self.is_valid:
            return ""
        return "; ".join(self.errors)


_REQUIRED_FILES = (
    "inference.yml",
    "inference.pdiparams",
)
_GRAPH_FILES = ("inference.json", "inference.pdmodel")


def _inspect_model(role: str, path: Path) -> OCRModelInfo:
    if not path.is_dir():
        return OCRModelInfo(role, path, None, False, "dossier absent")

    missing = [name for name in _REQUIRED_FILES if not (path / name).is_file()]
    if not any((path / name).is_file() for name in _GRAPH_FILES):
        missing.append("inference.json ou inference.pdmodel")
    if missing:
        return OCRModelInfo(
            role,
            path,
            None,
            False,
            "fichiers absents : " + ", ".join(missing),
        )

    config_path = path / "inference.yml"
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
    except Exception as exc:
        return OCRModelInfo(role, path, None, False, f"inference.yml illisible : {exc}")

    global_config = config.get("Global") if isinstance(config, dict) else None
    model_name = global_config.get("model_name") if isinstance(global_config, dict) else None
    if not isinstance(model_name, str) or not model_name.strip():
        return OCRModelInfo(
            role,
            path,
            None,
            False,
            "inference.yml ne contient pas Global.model_name",
        )

    return OCRModelInfo(role, path, model_name.strip(), True)


def validate_ocr_models(
    models_dir: ModelPath,
    *,
    require_orientation: bool = False,
) -> OCRModelValidation:
    """Inspecte les modèles embarqués sans charger PaddleOCR.

    Signature destinée au diagnostic API :
    ``validate_ocr_models(models_dir, *, require_orientation=False) -> OCRModelValidation``.
    ``files_present`` décrit uniquement les fichiers ; ``is_valid`` ne signifie
    pas qu'une instance PaddleOCR a été chargée. Le chargement réel est réalisé
    explicitement par :meth:`OCREngine._get_ocr`.
    """

    root = Path(models_dir).expanduser()
    orientation_path = root / "textline_orientation"
    orientation = (
        _inspect_model("textline_orientation", orientation_path)
        if orientation_path.exists() or require_orientation
        else None
    )
    return OCRModelValidation(
        root=root,
        detection=_inspect_model("text_detection", root / "text_detection"),
        recognition=_inspect_model("text_recognition", root / "text_recognition"),
        orientation=orientation,
        require_orientation=require_orientation,
    )
