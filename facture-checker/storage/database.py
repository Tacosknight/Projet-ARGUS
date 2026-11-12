"""
Module de persistance SQLite pour Facture-Checker.
Gère le schéma relationnel, les opérations CRUD, la détection d'unicité des factures
et l'indexation des numéros de série (S/N) pour le rapprochement Fournisseur/Client.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import hashlib
import logging
import sqlite3
from contextlib import closing
from core.data_lock import DATA_LOCK
import pandas as pd

logger = logging.getLogger("FactureChecker.Database")

DEFAULT_DB_PATH = "invoices.db"


class InvoiceConflict(ValueError):
    """Modification concurrente ou collision d'empreinte."""


def invoice_revision(row: Dict[str, Any]) -> str:
    payload = {k: v for k, v in dict(row).items() if k != "revision"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class InvoiceDatabase:
    """
    Gestionnaire de base de données SQLite pour l'archivage, l'audit
    et la réconciliation des factures (Fournisseurs et Clients).
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = str(db_path)
        self._ensure_parent_dir()
        self.init_db()

    def _ensure_parent_dir(self) -> None:
        parent = Path(self.db_path).parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Crée et retourne une connexion SQLite avec row_factory sqlite3.Row."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialise le schéma de la table invoices avec migration automatique des colonnes."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    invoice_type TEXT DEFAULT 'FOURNISSEUR',
                    document_type TEXT DEFAULT 'FACTURE',
                    related_invoice_id INTEGER,
                    siret TEXT,
                    siren TEXT,
                    numero_facture TEXT,
                    date_facture TEXT,
                    montant_ht REAL,
                    montant_tva REAL,
                    montant_ttc REAL,
                    tva_intracommunautaire TEXT,
                    fournisseur_nom TEXT,
                    patient_nom TEXT,
                    serial_numbers TEXT,
                    product_names TEXT,
                    product_items TEXT,
                    status TEXT NOT NULL,
                    error_details TEXT,
                    unique_hash TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    raw_text TEXT
                );
                """
            )

            # Migration automatique des colonnes si table préexistante
            existing_cols = {row["name"] for row in cursor.execute("PRAGMA table_info(invoices);")}
            if "source_documents" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN source_documents TEXT;")
            if "invoice_type" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN invoice_type TEXT DEFAULT 'FOURNISSEUR';")
            if "document_type" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN document_type TEXT DEFAULT 'FACTURE';")
            if "related_invoice_id" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN related_invoice_id INTEGER;")
            if "serial_numbers" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN serial_numbers TEXT;")
            if "product_names" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN product_names TEXT;")
            if "product_items" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN product_items TEXT;")
            if "patient_nom" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN patient_nom TEXT;")

            for column in ("emetteur_nom", "marque_produit"):
                if column not in existing_cols:
                    cursor.execute(f"ALTER TABLE invoices ADD COLUMN {column} TEXT;")

            # Indexations pour accélérer la recherche d'unicité, les types et les filtres
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_hash ON invoices(unique_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_siret ON invoices(siret);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_type ON invoices(invoice_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_related ON invoices(related_invoice_id);")
            cursor.execute("""CREATE TABLE IF NOT EXISTS direct_comparison_uploads (
                fingerprint TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL
            )""")
            conn.commit()

    def get_direct_upload(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        with DATA_LOCK, closing(self.get_connection()) as conn:
            row = conn.execute("SELECT invoice_id FROM direct_comparison_uploads WHERE fingerprint = ?", (fingerprint,)).fetchone()
            return self.get_invoice_by_id(row[0]) if row else None

    def is_hash_exists(self, unique_hash: str) -> bool:
        """
        Vérifie si une facture avec ce hash composite SHA-256 existe déjà en base.
        """
        if not unique_hash:
            return False
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM invoices WHERE unique_hash = ? OR unique_hash LIKE ? LIMIT 1;",
                (unique_hash, f"{unique_hash}%"),
            )
            return cursor.fetchone() is not None

    def save_invoice(self, data: Dict[str, Any]) -> int:
        """
        Enregistre ou met à jour une facture dans la table SQLite.

        Args:
            data (Dict[str, Any]): Dictionnaire contenant les champs extraits et validés.

        Returns:
            int: L'identifiant (ID) de la ligne insérée/mise à jour.
        """
        errors = data.get("error_details", [])
        if isinstance(errors, list):
            error_details_str = json.dumps(errors, ensure_ascii=False)
        else:
            error_details_str = str(errors)

        serials = data.get("serial_numbers", [])
        if isinstance(serials, list):
            serial_numbers_str = json.dumps(serials, ensure_ascii=False)
        else:
            serial_numbers_str = str(serials or "[]")

        products = data.get("product_names", [])
        if isinstance(products, list):
            product_names_str = json.dumps(products, ensure_ascii=False)
        else:
            product_names_str = str(products or "[]")

        product_items = data.get("product_items", [])
        product_items_str = json.dumps(product_items, ensure_ascii=False) if isinstance(product_items, list) else str(product_items or "[]")

        created_at = data.get("created_at") or datetime.now().isoformat()
        unique_hash = data.get("unique_hash")
        status = data.get("status", "A_VERIFIER")
        invoice_type = (data.get("invoice_type") or "FOURNISSEUR").upper()

        storage_hash = unique_hash
        if status == "DOUBLON" and unique_hash:
            storage_hash = f"{unique_hash}_dup_{data.get('filename', '')}"

        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO invoices (
                    filename,
                    invoice_type,
                    document_type,
                    related_invoice_id,
                    siret,
                    siren,
                    numero_facture,
                    date_facture,
                    montant_ht,
                    montant_tva,
                    montant_ttc,
                    tva_intracommunautaire,
                    fournisseur_nom,
                    emetteur_nom,
                    marque_produit,
                    patient_nom,
                    serial_numbers,
                    product_names,
                    product_items,
                    status,
                    error_details,
                    unique_hash,
                    created_at,
                    raw_text,
                    source_documents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_hash) DO UPDATE SET
                    filename = excluded.filename,
                    invoice_type = excluded.invoice_type,
                    document_type = excluded.document_type,
                    related_invoice_id = excluded.related_invoice_id,
                    status = excluded.status,
                    error_details = excluded.error_details,
                    montant_ht = excluded.montant_ht,
                    montant_tva = excluded.montant_tva,
                    montant_ttc = excluded.montant_ttc,
                    serial_numbers = excluded.serial_numbers,
                    product_names = excluded.product_names,
                    product_items = excluded.product_items,
                    source_documents = excluded.source_documents,
                    patient_nom = excluded.patient_nom,
                    emetteur_nom = COALESCE(invoices.emetteur_nom, excluded.emetteur_nom),
                    marque_produit = COALESCE(invoices.marque_produit, excluded.marque_produit),
                    created_at = excluded.created_at,
                    raw_text = excluded.raw_text;
                """,
                (
                    data.get("filename", "inconnu"),
                    invoice_type,
                    (data.get("document_type") or "FACTURE").upper(),
                    data.get("related_invoice_id"),
                    data.get("siret"),
                    data.get("siren"),
                    data.get("numero_facture"),
                    data.get("date_facture"),
                    data.get("montant_ht"),
                    data.get("montant_tva"),
                    data.get("montant_ttc"),
                    data.get("tva_intracommunautaire"),
                    data.get("fournisseur_nom"),
                    data.get("emetteur_nom"),
                    data.get("marque_produit"),
                    data.get("patient_nom") or data.get("client_nom"),
                    serial_numbers_str,
                    product_names_str,
                    product_items_str,
                    status,
                    error_details_str,
                    storage_hash,
                    created_at,
                    data.get("raw_text", ""),
                    json.dumps(data.get("source_documents", []), ensure_ascii=False),
                ),
            )
            invoice_id = cursor.lastrowid or 0
            if data.get("direct_upload_fingerprint"):
                cursor.execute("INSERT INTO direct_comparison_uploads (fingerprint, invoice_id) VALUES (?, ?) ON CONFLICT(fingerprint) DO UPDATE SET invoice_id = excluded.invoice_id",
                               (data["direct_upload_fingerprint"], invoice_id))
            conn.commit()
            return invoice_id

    def get_all_invoices(self) -> List[Dict[str, Any]]:
        """Retourne toutes les factures ordonnées par ID croissant."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices ORDER BY id ASC;")
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["marque_client"] = "Phoneme" if (item.get("invoice_type") or "").upper() == "CLIENT" else None
                item["source_documents"] = json.loads(item.get("source_documents") or "[]")
                if item.get("serial_numbers"):
                    try:
                        item["serial_numbers"] = json.loads(item["serial_numbers"])
                    except Exception:
                        pass
                if item.get("product_names"):
                    try:
                        item["product_names"] = json.loads(item["product_names"])
                    except Exception:
                        pass
                if item.get("product_items"):
                    try:
                        item["product_items"] = json.loads(item["product_items"])
                    except Exception:
                        item["product_items"] = []
                if item.get("page_current") is None or item.get("page_total") is None:
                    from core.multipage import detect_pagination
                    p_c, p_t = detect_pagination(item.get("raw_text", ""))
                    item["page_current"] = p_c
                    item["page_total"] = p_t
                results.append(item)
            return results


    def get_invoices_by_type(self, invoice_type: str) -> List[Dict[str, Any]]:
        """Filtre les factures selon leur type (FOURNISSEUR ou CLIENT)."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM invoices WHERE UPPER(invoice_type) = UPPER(?) ORDER BY id ASC;",
                (invoice_type,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["marque_client"] = "Phoneme" if (item.get("invoice_type") or "").upper() == "CLIENT" else None
                item["source_documents"] = json.loads(item.get("source_documents") or "[]")
                if item.get("serial_numbers"):
                    try:
                        item["serial_numbers"] = json.loads(item["serial_numbers"])
                    except Exception:
                        pass
                if item.get("product_names"):
                    try:
                        item["product_names"] = json.loads(item["product_names"])
                    except Exception:
                        pass
                if item.get("product_items"):
                    try:
                        item["product_items"] = json.loads(item["product_items"])
                    except Exception:
                        item["product_items"] = []
                results.append(item)
            return results

    def get_invoice_by_id(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        """Retourne une facture par son ID."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices WHERE id = ? LIMIT 1;", (invoice_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            item["revision"] = invoice_revision(item)
            item["marque_client"] = "Phoneme" if (item.get("invoice_type") or "").upper() == "CLIENT" else None
            item["source_documents"] = json.loads(item.get("source_documents") or "[]")
            if item.get("serial_numbers"):
                try:
                    item["serial_numbers"] = json.loads(item["serial_numbers"])
                except Exception:
                    pass
            if item.get("product_names"):
                try:
                    item["product_names"] = json.loads(item["product_names"])
                except Exception:
                    pass
            if item.get("product_items"):
                try:
                    item["product_items"] = json.loads(item["product_items"])
                except Exception:
                    item["product_items"] = []
            return item

    def update_invoice(self, invoice_id: int, updates: Dict[str, Any], expected_revision: Optional[str] = None) -> bool:
        """Fusionne, revalide et enregistre dans une seule transaction SQLite."""
        from core.validator import InvoiceValidator
        import math

        allowed = {"numero_facture", "date_facture", "montant_ht", "montant_tva", "montant_ttc",
                   "fournisseur_nom", "emetteur_nom", "marque_produit", "patient_nom", "invoice_type", "document_type", "related_invoice_id",
                   "serial_numbers", "product_names", "product_items", "siret", "siren", "tva_intracommunautaire"}
        if not updates or set(updates) - allowed:
            raise ValueError("Champs de mise à jour invalides.")
        with DATA_LOCK, closing(self.get_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if row is None:
                return False
            current = dict(row)
            if expected_revision is not None and invoice_revision(current) != expected_revision:
                raise InvoiceConflict("La facture a été modifiée depuis son ouverture.")
            merged = dict(current)
            merged.update(updates)
            for key in ("montant_ht", "montant_tva", "montant_ttc"):
                if merged[key] is not None:
                    try:
                        merged[key] = float(str(merged[key]).replace(",", ".").replace("€", "").strip())
                        if not math.isfinite(merged[key]):
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise ValueError(f"Montant invalide : {key}.")
            def duplicate(value):
                return conn.execute("SELECT 1 FROM invoices WHERE id != ? AND (unique_hash = ? OR substr(unique_hash, 1, ?) = ?) LIMIT 1",
                                    (invoice_id, value, len(value) + 5, value + "_dup_")).fetchone() is not None
            status, errors, new_hash = InvoiceValidator(db_is_duplicate_fn=duplicate).validate(merged)
            hash_fields = ("siret", "siren", "date_facture", "numero_facture", "montant_ttc")
            changed_hash = any(merged[k] != current[k] for k in hash_fields)
            if changed_hash and duplicate(new_hash):
                raise InvoiceConflict("Une autre facture possède cette empreinte métier.")
            # Les doublons historiques utilisent un suffixe : le conserver hors changement d'empreinte.
            stored_hash = new_hash if changed_hash else current["unique_hash"]
            changes = dict(updates, status=status, error_details=errors, unique_hash=stored_hash)
            for key in ("montant_ht", "montant_tva", "montant_ttc"):
                if key in changes:
                    changes[key] = merged[key]
            for key in ("serial_numbers", "product_names", "product_items", "error_details"):
                if key in changes:
                    changes[key] = json.dumps(changes[key], ensure_ascii=False)
            try:
                conn.execute("UPDATE invoices SET " + ", ".join(f"{key} = ?" for key in changes) + " WHERE id = ?",
                             (*changes.values(), invoice_id))
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise InvoiceConflict("Collision d'empreinte métier.") from exc
            return True

    def delete_invoice(self, invoice_id: int) -> bool:
        """Supprime une facture de la base par son ID."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM invoices WHERE id = ?;", (invoice_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_all_invoices(self) -> int:
        """Supprime toutes les factures de la base de données."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM invoices;")
            count = cursor.rowcount
            conn.commit()
            return count

    def get_invoices_df(self) -> pd.DataFrame:
        """Retourne toutes les factures sous forme de DataFrame pandas."""
        with DATA_LOCK, closing(self.get_connection()) as conn, conn:
            return pd.read_sql_query("SELECT * FROM invoices ORDER BY id ASC;", conn)


# Fonctions utilitaires au niveau module
def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    InvoiceDatabase(db_path).init_db()


def delete_invoice(invoice_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    return InvoiceDatabase(db_path).delete_invoice(invoice_id)


def clear_all_invoices(db_path: str = DEFAULT_DB_PATH) -> int:
    return InvoiceDatabase(db_path).clear_all_invoices()


def save_invoice(data: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    return InvoiceDatabase(db_path).save_invoice(data)


def update_invoice(invoice_id: int, updates: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> bool:
    return InvoiceDatabase(db_path).update_invoice(invoice_id, updates)


def get_invoice_by_id(invoice_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    return InvoiceDatabase(db_path).get_invoice_by_id(invoice_id)


def is_hash_exists(unique_hash: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    return InvoiceDatabase(db_path).is_hash_exists(unique_hash)


def get_all_invoices(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    return InvoiceDatabase(db_path).get_all_invoices()


def get_invoices_df(db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    return InvoiceDatabase(db_path).get_invoices_df()
