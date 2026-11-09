"""Valider les modèles depuis le checkout de confiance, sans code interpolé."""
import argparse
import importlib.util
from pathlib import Path
import sys

# Charger uniquement le validateur : core/__init__.py importe aussi OpenCV et
# d'autres dépendances lourdes inutiles à cette validation statique.
module_path = Path(__file__).resolve().parent.parent / "facture-checker" / "core" / "ocr_models.py"
spec = importlib.util.spec_from_file_location("argus_ocr_models_validation", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
validate_ocr_models = module.validate_ocr_models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("models", type=Path)
    args = parser.parse_args()
    result = validate_ocr_models(args.models)
    if not result.is_valid:
        parser.exit(1, result.error_message() + "\n")
    print(result.model_names)


if __name__ == "__main__":
    main()
