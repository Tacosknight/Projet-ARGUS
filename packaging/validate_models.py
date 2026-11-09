"""Valider les modèles depuis le checkout de confiance, sans code interpolé."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "facture-checker"))
from core.ocr_models import validate_ocr_models


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
