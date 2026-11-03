"""
Module de persistance SQLite pour Facture-Checker.
Gère le schéma relationnel, les opérations CRUD, la détection d'unicité des factures
et l'indexation des numéros de série (S/N) pour le rapprochement Fournisseur/Client.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import sqlite3
import pandas as pd

logger = logging.getLogger("FactureChecker.Database")

DEFAULT_DB_PATH = "invoices.db"


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
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    invoice_type TEXT DEFAULT 'FOURNISSEUR',
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
            if "invoice_type" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN invoice_type TEXT DEFAULT 'FOURNISSEUR';")
            if "serial_numbers" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN serial_numbers TEXT;")
            if "patient_nom" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN patient_nom TEXT;")

            # Indexations pour accélérer la recherche d'unicité, les types et les filtres
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_hash ON invoices(unique_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_siret ON invoices(siret);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_type ON invoices(invoice_type);")
            conn.commit()

    def is_hash_exists(self, unique_hash: str) -> bool:
        """
        Vérifie si une facture avec ce hash composite SHA-256 existe déjà en base.
        """
        if not unique_hash:
            return False
        with self.get_connection() as conn:
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

        created_at = data.get("created_at") or datetime.now().isoformat()
        unique_hash = data.get("unique_hash")
        status = data.get("status", "A_VERIFIER")
        invoice_type = (data.get("invoice_type") or "FOURNISSEUR").upper()

        storage_hash = unique_hash
        if status == "DOUBLON" and unique_hash:
            storage_hash = f"{unique_hash}_dup_{data.get('filename', '')}"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO invoices (
                    filename,
                    invoice_type,
                    siret,
                    siren,
                    numero_facture,
                    date_facture,
                    montant_ht,
                    montant_tva,
                    montant_ttc,
                    tva_intracommunautaire,
                    fournisseur_nom,
                    patient_nom,
                    serial_numbers,
                    status,
                    error_details,
                    unique_hash,
                    created_at,
                    raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unique_hash) DO UPDATE SET
                    filename = excluded.filename,
                    invoice_type = excluded.invoice_type,
                    status = excluded.status,
                    error_details = excluded.error_details,
                    montant_ht = excluded.montant_ht,
                    montant_tva = excluded.montant_tva,
                    montant_ttc = excluded.montant_ttc,
                    serial_numbers = excluded.serial_numbers,
                    patient_nom = excluded.patient_nom,
                    created_at = excluded.created_at,
                    raw_text = excluded.raw_text;
                """,
                (
                    data.get("filename", "inconnu"),
                    invoice_type,
                    data.get("siret"),
                    data.get("siren"),
                    data.get("numero_facture"),
                    data.get("date_facture"),
                    data.get("montant_ht"),
                    data.get("montant_tva"),
                    data.get("montant_ttc"),
                    data.get("tva_intracommunautaire"),
                    data.get("fournisseur_nom"),
                    data.get("patient_nom") or data.get("client_nom"),
                    serial_numbers_str,
                    status,
                    error_details_str,
                    storage_hash,
                    created_at,
                    data.get("raw_text", ""),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def get_all_invoices(self) -> List[Dict[str, Any]]:
        """Retourne toutes les factures ordonnées par ID croissant."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invoices ORDER BY id ASC;")
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("serial_numbers"):
                    try:
                        item["serial_numbers"] = json.loads(item["serial_numbers"])
                    except Exception:
                        pass
                if item.get("page_current") is None or item.get("page_total") is None:
                    from core.multipage import detect_pagination
                    p_c, p_t = detect_pagination(item.get("raw_text", ""))
                    item["page_current"] = p_c
                    item["page_total"] = p_t
                results.append(item)
            return results


    def get_invoices_by_type(self, invoice_type: str) -> List[Dict[str, Any]]:
        """Filtre les factures selon leur type (FOURNISSEUR ou CLIENT)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM invoices WHERE UPPER(invoice_type) = UPPER(?) ORDER BY id ASC;",
                (invoice_type,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("serial_numbers"):
                    try:
                        item["serial_numbers"] = json.loads(item["serial_numbers"])
                    except Exception:
                        pass
                results.append(item)
            return results

    def delete_invoice(self, invoice_id: int) -> bool:
        """Supprime une facture de la base par son ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM invoices WHERE id = ?;", (invoice_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_invoices_df(self) -> pd.DataFrame:
        """Retourne toutes les factures sous forme de DataFrame pandas."""
        with self.get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM invoices ORDER BY id ASC;", conn)


# Fonctions utilitaires au niveau module
def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    InvoiceDatabase(db_path).init_db()


def save_invoice(data: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    return InvoiceDatabase(db_path).save_invoice(data)


def is_hash_exists(unique_hash: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    return InvoiceDatabase(db_path).is_hash_exists(unique_hash)


def get_all_invoices(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    return InvoiceDatabase(db_path).get_all_invoices()


def get_invoices_df(db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    return InvoiceDatabase(db_path).get_invoices_df()
