# acpof_pages/imports/import_data.py
import sqlite3
import pandas as pd
import streamlit as st
from typing import Dict, List, Tuple

# --------------------- CONFIG BD ---------------------
DB_PATH = "acpof.db"  # adapte si tu utilises un chemin différent / Supabase

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_schema(conn):
    # Table ingrédients
    conn.execute("""
    CREATE TABLE IF NOT EXISTS ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        supplier TEXT,
        supplier_code TEXT,
        unit_qty REAL,         -- e (ex: 1000)
        base_unit TEXT,        -- f (ex: g, ml, unité)
        purchase_qty REAL,     -- g (ex: 1, 6, 12)
        purchase_unit TEXT,    -- h (ex: kg, L, caisse)
        purchase_price REAL,   -- i (prix total pour le format d'achat)
        unit_price REAL,       -- j (calculé si manquant)
        UNIQUE(supplier, supplier_code)
    )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ingredients_name ON ingredients(name)")

    # Table recettes
    conn.execute("""
    CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        yield_qty REAL,           -- optionnel
        yield_unit TEXT           -- optionnel
    )
    """)

    # Table de liaison recette <-> ingrédients (format "long")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL,
        qty REAL NOT NULL,
        unit TEXT,
        notes TEXT,
        FOREIGN KEY(recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
    )
    """)
    conn.commit()

# --------------------- OUTILS ---------------------
REQUIRED_ING_FIELDS = {
    "name": ["Nom du produit", "nom", "produit", "name"],
    "category": ["Catégorie", "categorie", "category"],
    "supplier": ["Fournisseur", "supplier"],
    "supplier_code": ["Code produit fournisseur", "code", "sku", "supplier_code"],
    "unit_qty": ["Qté unitaire", "qte unitaire", "unitaire", "unit_qty"],
    "base_unit": ["Format de base", "format de base", "base_unit"],
    "purchase_qty": ["Qté format achat", "qte format achat", "purchase_qty"],
    "purchase_unit": ["Format achat", "format achat", "purchase_unit"],
    "purchase_price": ["Prix d'achat", "prix d'achat", "prix achat", "purchase_price"],
    "unit_price": ["Prix unitaire (optionnel)", "prix unitaire", "unit_price"],
}

RECIPE_FIELDS = {
    "recipe_name": ["Recette", "recipe", "nom recette", "name"],
    "yield_qty": ["Portions/poids", "portion", "yield_qty"],
    "yield_unit": ["Unité de portion", "unité portion", "yield_unit"],
    "ingredient_name": ["Ingrédient", "ingredient", "Nom du produit"],
    "qty": ["Quantité", "quantite", "qty"],
    "unit": ["Unité", "unite", "unit"],
    "notes": ["Notes (optionnel)", "notes"],
}

def auto_map_columns(cols: List[str], candidates: Dict[str, List[str]]) -> Dict[str, str]:
    mapping = {}
    lower = {c.lower(): c for c in cols}
    for canonical, names in candidates.items():
        chosen = None
        for n in names:
            if n.lower() in lower:
                chosen = lower[n.lower()]
                break
        mapping[canonical] = chosen
    return mapping

def ensure_numeric(df: pd.DataFrame, cols: List[str]):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

def compute_unit_price(row) -> float:
    # si unit_price manquant, on tente: prix d'achat / (Qté format achat * Qté unitaire)
    if pd.notna(row.get("unit_price")):
        return row["unit_price"]
    try:
        pq = float(row.get("purchase_qty") or 0)
        uq = float(row.get("unit_qty") or 0)
        price = float(row.get("purchase_price") or 0)
        if pq > 0 and uq > 0 and price > 0:
            return price / (pq * uq)
    except Exception:
        pass
    return None

# --------------------- UPSERT / INSERT ---------------------
def upsert_ingredient(conn, row: dict) -> int:
    # essaie d’upsert par (supplier, supplier_code) sinon par name
    # 1) si supplier_code présent
    if row.get("supplier") and row.get("supplier_code"):
        cur = conn.execute("""
            SELECT id FROM ingredients WHERE supplier=? AND supplier_code=?
        """, (row["supplier"], row["supplier_code"]))
        r = cur.fetchone()
        if r:
            conn.execute("""
                UPDATE ingredients
                SET name=?, category=?, unit_qty=?, base_unit=?, purchase_qty=?, purchase_unit=?, purchase_price=?, unit_price=?
                WHERE id=?
            """, (row["name"], row.get("category"), row.get("unit_qty"), row.get("base_unit"),
                  row.get("purchase_qty"), row.get("purchase_unit"), row.get("purchase_price"),
                  row.get("unit_price"), r[0]))
            return r[0]

    # 2) fallback: par name
    cur = conn.execute("SELECT id FROM ingredients WHERE name=?", (row["name"],))
    r = cur.fetchone()
    if r:
        conn.execute("""
            UPDATE ingredients
            SET category=?, supplier=?, supplier_code=?, unit_qty=?, base_unit=?, purchase_qty=?, purchase_unit=?, purchase_price=?, unit_price=?
            WHERE id=?
        """, (row.get("category"), row.get("supplier"), row.get("supplier_code"),
              row.get("unit_qty"), row.get("base_unit"), row.get("purchase_qty"),
              row.get("purchase_unit"), row.get("purchase_price"), row.get("unit_price"), r[0]))
        return r[0]

    cur = conn.execute("""
        INSERT INTO ingredients (name, category, supplier, supplier_code, unit_qty, base_unit, purchase_qty, purchase_unit, purchase_price, unit_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (row["name"], row.get("category"), row.get("supplier"), row.get("supplier_code"),
          row.get("unit_qty"), row.get("base_unit"), row.get("purchase_qty"),
          row.get("purchase_unit"), row.get("purchase_price"), row.get("unit_price")))
    return cur.lastrowid

def get_or_create_recipe(conn, name: str, yield_qty: float|None, yield_unit: str|None) -> int:
    cur = conn.execute("SELECT id FROM recipes WHERE name=?", (name,))
    r = cur.fetchone()
    if r:
        # met à jour le rendement si fourni
        if yield_qty is not None or yield_unit is not None:
            conn.execute("UPDATE recipes SET yield_qty=?, yield_unit=? WHERE id=?",
                         (yield_qty, yield_unit, r[0]))
        return r[0]
    cur = conn.execute("INSERT INTO recipes (name, yield_qty, yield_unit) VALUES (?, ?, ?)",
                       (name, yield_qty, yield_unit))
    return cur.lastrowid

def find_ingredient_id(conn, name: str) -> int|None:
    cur = conn.execute("SELECT id FROM ingredients WHERE name=?", (name,))
    r = cur.fetchone()
    return r[0] if r else None

def add_recipe_ingredient(conn, recipe_id: int, ingredient_id: int, qty: float, unit: str|None, notes: str|None):
    conn.execute("""
        INSERT INTO recipe_ingredients (recipe_id, ingredient_id, qty, unit, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (recipe_id, ingredient_id, qty, unit, notes))

# --------------------- UI ---------------------
def render_ingredients_tab(conn):
    st.subheader("Importer des ingrédients (.csv)")
    uploaded = st.file_uploader("Choisir un fichier CSV d’ingrédients", type=["csv"], key="ing_csv")
    if not uploaded:
        st.info("Utilise le gabarit ‘template_ingredients.csv’ si tu veux : colonnes prénommées et exemples.")
        return

    df = pd.read_csv(uploaded)
    st.caption(f"{len(df)} lignes détectées")
    with st.expander("Aperçu brut"):
        st.dataframe(df.head(20), use_container_width=True)

    # Mapping de colonnes
    st.write("**Mappage des colonnes** (corrige si besoin)")
    auto = auto_map_columns(df.columns.tolist(), REQUIRED_ING_FIELDS)
    mapping = {}
    cols = df.columns.tolist()
    for canonical, default_col in auto.items():
        mapping[canonical] = st.selectbox(
            f"{canonical}",
            options=["--Aucune--"] + cols,
            index=(cols.index(default_col)+1 if default_col in cols else 0),
            key=f"map_ing_{canonical}"
        )

    # Appliquer le mapping
    sel = {k: v for k, v in mapping.items() if v and v != "--Aucune--"}
    missing = [k for k in ["name", "supplier", "purchase_price"] if k not in sel]
    if missing:
        st.warning(f"Champs minimaux requis manquants: {', '.join(missing)} (tu peux importer, mais certaines lignes seront ignorées).")

    # Dataframe normalisé
    norm_cols = ["name","category","supplier","supplier_code","unit_qty","base_unit","purchase_qty","purchase_unit","purchase_price","unit_price"]
    nd = pd.DataFrame({k: (df[v] if k in sel else pd.NA) for k,v in sel.items()})
    for k in norm_cols:
        if k not in nd.columns:
            nd[k] = pd.NA
    ensure_numeric(nd, ["unit_qty","purchase_qty","purchase_price","unit_price"])
    nd["unit_price"] = nd.apply(compute_unit_price, axis=1)

    with st.expander("Aperçu normalisé (prêt à importer)"):
        st.dataframe(nd.head(50), use_container_width=True)

    # Importer
    if st.button("Importer les ingrédients", type="primary"):
        inserted, updated, skipped = 0, 0, 0
        for _, r in nd.iterrows():
            try:
                if pd.isna(r.get("name")) or pd.isna(r.get("supplier")):
                    skipped += 1
                    continue
                row = {k: (None if pd.isna(r[k]) else r[k]) for k in norm_cols}
                before = conn.execute(
                    "SELECT id, name, supplier, supplier_code FROM ingredients WHERE (supplier=? AND supplier_code=?) OR name=?",
                    (row.get("supplier"), row.get("supplier_code"), row.get("name"))
                ).fetchone()
                iid = upsert_ingredient(conn, row)
                after = conn.execute("SELECT id FROM ingredients WHERE id=?", (iid,)).fetchone()
                if before is None and after is not None:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                skipped += 1
        conn.commit()
        st.success(f"Ingrédients importés ✅  — Ajouts: {inserted}, Mises à jour: {updated}, Ignorés: {skipped}")

def render_recipes_tab(conn):
    st.subheader("Importer des recettes (.csv) – format ‘long’")
    uploaded = st.file_uploader("Choisir un fichier CSV de recettes", type=["csv"], key="rec_csv")
    if not uploaded:
        st.info("Utilise le gabarit ‘template_recettes.csv’ : chaque ligne = 1 ingrédient d’une recette.")
        return

    df = pd.read_csv(uploaded)
    st.caption(f"{len(df)} lignes détectées")
    with st.expander("Aperçu brut"):
        st.dataframe(df.head(20), use_container_width=True)

    # Mapping colonnes
    st.write("**Mappage des colonnes** (corrige si besoin)")
    auto = auto_map_columns(df.columns.tolist(), RECIPE_FIELDS)
    mapping = {}
    cols = df.columns.tolist()
    for canonical, default_col in auto.items():
        mapping[canonical] = st.selectbox(
            f"{canonical}",
            options=["--Aucune--"] + cols,
            index=(cols.index(default_col)+1 if default_col in cols else 0),
            key=f"map_rec_{canonical}"
        )

    sel = {k: v for k, v in mapping.items() if v and v != "--Aucune--"}
    # Normalise
    nd = pd.DataFrame({
        "recipe_name": df[sel.get("recipe_name")] if sel.get("recipe_name") else pd.NA,
        "yield_qty": pd.to_numeric(df[sel.get("yield_qty")], errors="coerce") if sel.get("yield_qty") else pd.NA,
        "yield_unit": df[sel.get("yield_unit")] if sel.get("yield_unit") else pd.NA,
        "ingredient_name": df[sel.get("ingredient_name")] if sel.get("ingredient_name") else pd.NA,
        "qty": pd.to_numeric(df[sel.get("qty")], errors="coerce") if sel.get("qty") else pd.NA,
        "unit": df[sel.get("unit")] if sel.get("unit") else pd.NA,
        "notes": df[sel.get("notes")] if sel.get("notes") else pd.NA,
    })

    with st.expander("Aperçu normalisé"):
        st.dataframe(nd.head(50), use_container_width=True)

    # Rapport d’ingrédients manquants
    missing_ings = sorted({n for n in nd["ingredient_name"].dropna().unique()
                           if not find_ingredient_id(conn, str(n))})
    if missing_ings:
        st.warning("Certains ingrédients listés n’existent pas encore en BD. Ils seront ignorés pour l’instant :")
        st.code("\n".join(missing_ings)[:2000])

    if st.button("Importer les recettes", type="primary"):
        created_r, added_lines, skipped = 0, 0, 0
        for _, r in nd.iterrows():
            try:
                rn = str(r.get("recipe_name")) if pd.notna(r.get("recipe_name")) else None
                ingn = str(r.get("ingredient_name")) if pd.notna(r.get("ingredient_name")) else None
                if not rn or not ingn or pd.isna(r.get("qty")):
                    skipped += 1
                    continue
                recipe_id = get_or_create_recipe(conn, rn,
                                                 float(r.get("yield_qty")) if pd.notna(r.get("yield_qty")) else None,
                                                 str(r.get("yield_unit")) if pd.notna(r.get("yield_unit")) else None)
                ing_id = find_ingredient_id(conn, ingn)
                if not ing_id:
                    skipped += 1
                    continue
                add_recipe_ingredient(conn, recipe_id, ing_id,
                                      float(r.get("qty")) if pd.notna(r.get("qty")) else 0.0,
                                      (str(r.get("unit")) if pd.notna(r.get("unit")) else None),
                                      (str(r.get("notes")) if pd.notna(r.get("notes")) else None))
                added_lines += 1
            except Exception:
                skipped += 1
        conn.commit()
        st.success(f"Recettes importées ✅ — Lignes ajoutées: {added_lines}, Lignes ignorées: {skipped}")

# --------------------- PAGE ---------------------
def imports_page():
    st.title("Import CSV — Ingrédients & Recettes")
    conn = get_conn()
    init_schema(conn)
    tab1, tab2 = st.tabs(["📦 Ingrédients", "📖 Recettes"])
    with tab1:
        render_ingredients_tab(conn)
    with tab2:
        render_recipes_tab(conn)

if __name__ == "__main__":
    imports_page()

