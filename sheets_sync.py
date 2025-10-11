# sheets_sync.py
from __future__ import annotations
import io
from typing import Iterable, List, Dict, Any, Tuple
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

TABLES = {
    # nom_onglet : (colonnes dans l'ordre)
    "suppliers": ["id", "name", "contact", "phone", "email", "notes"],
    "ingredients": [
        "id", "name", "category", "supplier_id",
        "pack_size", "pack_unit", "purchase_price",
        "price_per_base_unit", "base_unit", "created_at",
    ],
    "recipes": ["id", "name", "category", "servings", "instructions"],
    "recipe_items": ["id", "recipe_id", "ingredient_id", "quantity", "unit"],
    "stock_movements": ["id", "ingredient_id", "qty", "unit", "movement_type", "notes", "created_at"],
    "menus": ["id", "name", "notes"],
    "menu_items": ["id", "menu_id", "recipe_id", "batches"],
}

# ------------- Auth + ouverture du spreadsheet -------------
def _gc() -> gspread.Client:
    info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPE)
    return gspread.authorize(creds)

def _open_spreadsheet():
    gc = _gc()
    name = st.secrets["sheets"]["spreadsheet_name"]
    try:
        return gc.open(name)
    except gspread.SpreadsheetNotFound:
        # créer si absent
        sh = gc.create(name)
        # partage au compte de service pas nécessaire (il en est “proprio”), mais à ton compte Google si tu veux le voir dans ton Drive:
        # sh.share("ton-email@gmail.com", perm_type="user", role="writer")
        return sh

def _get_ws(sh, title: str):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=2000, cols=40)

# ------------- utilitaires -------------
def _ensure_headers(ws, headers: List[str]) -> None:
    # Regarde la première ligne ; si différente, la réécrit
    has = ws.row_values(1)
    if has != headers:
        ws.clear()
        ws.update("1:1", [headers])

def _rows_from_dicts(items: Iterable[Dict[str, Any]], headers: List[str]) -> List[List[Any]]:
    out = []
    for obj in items:
        row = [obj.get(col, "") for col in headers]
        out.append(row)
    return out

def _dicts_from_rows(rows: List[List[Any]], headers: List[str]) -> List[Dict[str, Any]]:
    dicts = []
    for r in rows:
        d = {}
        for i, col in enumerate(headers):
            d[col] = r[i] if i < len(r) else ""
        dicts.append(d)
    return dicts

# ------------- Export (DB -> Sheets) -------------
def export_table_from_db(db, table_name: str) -> int:
    """
    Exporte une table SQLAlchemy vers l'onglet Sheets (écrasement complet).
    Retourne le nombre de lignes écrites (hors entête).
    """
    if table_name not in TABLES:
        raise ValueError(f"Table inconnue: {table_name}")

    headers = TABLES[table_name]
    # Récupérer les lignes depuis la DB (via SQL brut pour robustesse)
    rows = db.execute(f"SELECT {', '.join(headers)} FROM {table_name}").fetchall()
    dicts = [dict(zip(headers, row)) for row in rows]

    sh = _open_spreadsheet()
    ws = _get_ws(sh, table_name)
    _ensure_headers(ws, headers)

    if dicts:
        values = _rows_from_dicts(dicts, headers)
        ws.update(f"A2", values)  # colle à partir de A2
        # Nettoyage des lignes en trop (si la feuille contenait plus avant)
        last_row = 1 + len(values)
        all_rows = ws.row_count
        if last_row < all_rows:
            ws.resize(rows=last_row)
    else:
        # pas de données : on réinitialise à juste l'entête + 1 ligne
        ws.resize(rows=2)

    return len(dicts)

def export_all_tables(db) -> Dict[str, int]:
    res = {}
    for t in TABLES:
        try:
            res[t] = export_table_from_db(db, t)
        except Exception as e:
            res[t] = -1
    return res

# ------------- Import (Sheets -> DB) -------------
def import_table_to_db(db, table_name: str) -> int:
    """
    Importe (remplacement complet) l’onglet Sheets dans la table DB.
    ATTENTION : fait un TRUNCATE logique (DELETE) avant réinsertion.
    """
    if table_name not in TABLES:
        raise ValueError(f"Table inconnue: {table_name}")

    headers = TABLES[table_name]
    sh = _open_spreadsheet()
    ws = _get_ws(sh, table_name)
    _ensure_headers(ws, headers)

    data = ws.get_all_values()
    if not data or len(data) <= 1:
        # uniquement l'entête
        db.execute(f"DELETE FROM {table_name}")
        db.commit()
        return 0

    body = data[1:]  # sans l’entête
    dicts = _dicts_from_rows(body, headers)

    # wipe + insert
    db.execute(f"DELETE FROM {table_name}")
    # construction de l’INSERT
    placeholders = ", ".join([f":{c}" for c in headers])
    sql = f"INSERT INTO {table_name} ({', '.join(headers)}) VALUES ({placeholders})"
    db.execute(sql, dicts)
    db.commit()
    return len(dicts)

def import_all_tables(db) -> Dict[str, int]:
    res = {}
    for t in TABLES:
        try:
            res[t] = import_table_to_db(db, t)
        except Exception as e:
            res[t] = -1
    return res
