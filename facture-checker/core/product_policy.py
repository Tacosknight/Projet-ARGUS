"""Exclusion non destructive des appareils de démonstration et d'essai."""

import json
import re
import unicodedata
from typing import Any, Dict, List


def non_sale_reason(label: Any) -> str:
    """Reconnaît des mots entiers, pas des modèles contenant ces lettres."""
    text = unicodedata.normalize("NFKD", str(label or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    match = re.search(r"\b(demo|trial)\b", text, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def is_non_sale_item(item: Dict[str, Any]) -> bool:
    return bool(
        item.get("non_sale_reason") in ("demo", "trial")
        or non_sale_reason(item.get("product_name"))
        or non_sale_reason(item.get("designation"))
    )


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except ValueError:
            return [value] if value else []
    return []


def billable_products(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Vue métier ; les données OCR originales ne sont jamais modifiées.

    Les séries et noms des articles exclus sont aussi retirés des listes de
    secours, sauf s'ils appartiennent également à un article commercial.
    """
    items = _as_list(invoice.get("product_items"))
    kept = [item for item in items if isinstance(item, dict) and not is_non_sale_item(item)]
    excluded = [item for item in items if isinstance(item, dict) and is_non_sale_item(item)]

    def serial(item):
        return str(item.get("serial_number") or "").strip().upper()

    def names(entries):
        return {str(item[key]).strip() for item in entries for key in ("product_name", "designation") if item.get(key)}

    excluded_serials = {serial(item) for item in excluded} - {serial(item) for item in kept}
    excluded_names = names(excluded) - names(kept)
    product_names = [
        name for name in _as_list(invoice.get("product_names"))
        if not non_sale_reason(name) and str(name).strip() not in excluded_names
    ]
    serials = [
        value for value in _as_list(invoice.get("serial_numbers"))
        if str(value).strip().upper() not in excluded_serials
    ]
    return {
        **invoice,
        "product_items": kept,
        "product_names": product_names,
        "serial_numbers": serials,
    }


def has_non_sale_products(invoice: Dict[str, Any]) -> bool:
    return any(is_non_sale_item(item) for item in _as_list(invoice.get("product_items")) if isinstance(item, dict)) or any(
        non_sale_reason(name) for name in _as_list(invoice.get("product_names"))
    )
