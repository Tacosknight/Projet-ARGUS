"""
Module core pour Facture-Checker.
Contient le pipeline de vision par ordinateur, OCR, parsing et validation.
"""

from .preprocessor import preprocess_image, four_point_transform
from .ocr_engine import OCRInferenceError, OCRModelError, OCREngine, extract_text_and_boxes
from .ocr_models import OCRModelValidation, validate_ocr_models
from .parser import InvoiceParser, parse_invoice
from .validator import InvoiceValidator
from .reconciliation import ReconciliationEngine, reconcile_invoices

__all__ = [
    "preprocess_image",
    "four_point_transform",
    "OCREngine",
    "OCRInferenceError",
    "OCRModelError",
    "OCRModelValidation",
    "validate_ocr_models",
    "extract_text_and_boxes",
    "InvoiceParser",
    "parse_invoice",
    "InvoiceValidator",
    "ReconciliationEngine",
    "reconcile_invoices",
]
