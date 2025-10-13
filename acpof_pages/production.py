# ACPOF – Module Production (Streamlit) + SQL
# --------------------------------------------------------------
# Ce fichier contient :
# 1) Les scripts SQL (création/migration) pour le registre de production
# 2) Une page Streamlit complète à intégrer à votre app (ex.: acpof_pages/production.py)
#    - Création de lots (produits maison / productions à forfait)
#    - Saisie pH J0 & J14
#    - Journal des lots + sorties d'inventaire
#    - Ingrédients auto-ajoutés à partir de la recette choisie
#
# Hypothèses de BD existantes :
#   - recipes(id, name, yield_qty, yield_unit, ...)
#   - recipe_ingredients(recipe_id, ingredient_id, qty, unit)
#   - ingredients(id, name, default_unit, ...)
#   - products(id, name, sku, default_format, default_unit, ...)
# (Adaptez les noms de colonnes au besoin; les fonctions de mapping sont isolées.)
# --------------------------------------------------------------

SQL_MIGRATIONS = r"""
-- Clients (utilisé si production à forfait)
CREATE TABLE IF NOT EXISTS clients (
  client_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  contact TEXT,
  phone TEXT,
  email TEXT,
  notes TEXT
);

-- Lots de production (produits finis)
CREATE TABLE IF NOT EXISTS production_batches (
  batch_id INTEGER PRIMARY KEY,
  lot_code TEXT UNIQUE NOT NULL,
  produced_at DATE NOT NULL,
  recipe_id INTEGER,
  product_id INTEGER,
  production_type TEXT CHECK (production_type IN ('maison','forfait')) NOT NULL,
  client_id INTEGER,
  quantity REAL NOT NULL,
  unit TEXT NOT NULL,
  format TEXT,
  responsible TEXT,
  status TEXT CHECK (status IN ('J0','J14','conforme','non_conforme')) NOT NULL DEFAULT 'J0',
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (recipe_id) REFERENCES recipes(id),
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

-- Mesures de pH / contrôles
CREATE TABLE IF NOT EXISTS batch_tests (
  test_id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  test_type TEXT CHECK (test_type IN ('pH','temp','aw','visuel')) NOT NULL,
  test_day INTEGER,            -- 0, 14, etc.
  value REAL,                  -- pH ou valeur numérique
  result TEXT,                 -- 'OK','À risque','Non conforme','N/A'
  notes TEXT,
  tested_at DATE NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES production_batches(batch_id)
);

-- Lien avec ingrédients (traçabilité amont)
CREATE TABLE IF NOT EXISTS batch_inputs (
  input_id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  ingredient_id INTEGER NOT NULL,
  qty_used REAL NOT NULL,
  unit TEXT NOT NULL,
  supplier_lot TEXT,           -- # lot fournisseur (optionnel)
  FOREIGN KEY (batch_id) REFERENCES production_batches(batch_id),
  FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

-- Inventaire des produits finis par lot
CREATE TABLE IF NOT EXISTS finished_inventory (
  inv_id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  delta REAL NOT NULL,         -- + à la prod, - à la vente/perte
  unit TEXT NOT NULL,
  reason TEXT,                 -- 'production','vente','rebut','don','ajustement'
  at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (batch_id) REFERENCES production_batches(batch_id)
);

-- Cibles pH par recette/produit (facultatif, pour auto-statut)
CREATE TABLE IF NOT EXISTS product_targets (
  target_id INTEGER PRIMARY KEY,
  recipe_id INTEGER,
  product_id INTEGER,
  ph_max REAL,                 -- ex.: 4.6 (adapter par produit)
  UNIQUE(recipe_id, product_id)
);
"""

# --------------------------------------------------------------
# STREAMLIT PAGE
# --------------------------------------------------------------
import sqlite3
import datetime as dt
from typing import List, Tuple, Optional
import streamlit as st

DB_PATH = 'atelier.db'  # adaptez si nécessaire

# -------------------- Utils BD --------------------

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@st.cache_resource(show_spinner=False)
def init_db_and_migrate():
    conn = get_conn()
    c = conn.cursor()
    for stmt in SQL_MIGRATIONS.split(';'):
        s = stmt.strip()
        if s:
            c.execute(s)
    conn.commit()
    return conn

conn = init_db_and_migrate()

def q(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    return rows

# -------------------- Sélecteurs de données existantes --------------------

def get_recipe_options(conn) -> List[Tuple[int, str]]:
    rows = q(conn, "SELECT id, name FROM recipes ORDER BY name")
    return [(r[0], r[1]) for r in rows]

def get_product_options(conn) -> List[Tuple[Optional[int], str]]:
    rows = q(conn, "SELECT id, COALESCE(sku || ' – ', '') || name FROM products ORDER BY name")
    return [(r[0], r[1]) for r in rows]

def get_client_options(conn) -> List[Tuple[Optional[int], str]]:
    rows = q(conn, "SELECT client_id, name FROM clients ORDER BY name")
    return [(None, '— Aucun —')] + [(r[0], r[1]) for r in rows]

# -------------------- Recettes → ingrédients --------------------

def get_recipe_ingredients(conn, recipe_id: int):
    """Retourne liste de dicts: [{ingredient_id, name, qty, unit}] pour 1x rendement recette."""
    sql = (
        "SELECT ri.ingredient_id, i.name, ri.qty, ri.unit "
        "FROM recipe_ingredients ri "
        "JOIN ingredients i ON i.id = ri.ingredient_id "
        "WHERE ri.recipe_id = ? ORDER BY i.name"
    )
    rows = q(conn, sql, (recipe_id,))
    return [
        {"ingredient_id": r[0], "name": r[1], "qty": float(r[2] or 0), "unit": r[3]}
        for r in rows
    ]

# -------------------- Logique lot --------------------

def next_short_lot_code(conn, produced_at: str) -> str:
    """
    Lot court non-identifiable client :
    Format: LYYMMDD-NN  (ex.: L251013-03)
    - YYMMDD = date de prod
    - NN     = compteur du jour (2 chiffres, 01-99)
    """
    d = dt.datetime.strptime(produced_at, "%Y-%m-%d")
    prefix = f"L{d.strftime('%y%m%d')}"
    like_prefix = f"{prefix}-%"
    rows = q(conn, "SELECT lot_code FROM production_batches WHERE lot_code LIKE ? ORDER BY lot_code DESC LIMIT 1", (like_prefix,))
    if not rows:
        return f"{prefix}-01"
    last = rows[0][0].split('-')[-1]
    nn = int(last) + 1
    return f"{prefix}-{nn:02d}"


def create_batch(conn, produced_at: str, recipe_id: Optional[int], product_id: Optional[int],
                 production_type: str, client_id: Optional[int], quantity: float, unit: str,
                 format_: str, responsible: str, notes: str) -> Tuple[int, str]:
    lot_code = next_short_lot_code(conn, produced_at)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO production_batches(
          lot_code, produced_at, recipe_id, product_id, production_type, client_id,
          quantity, unit, format, responsible, status, notes
        ) VALUES(?,?,?,?,?,?,?,?,?,?,'J0',?)
        """,
        (lot_code, produced_at, recipe_id, product_id, production_type, client_id,
         quantity, unit, format_, responsible, notes)
    )
    batch_id = c.lastrowid

    # Inventaire +Q à la création
    c.execute("INSERT INTO finished_inventory(batch_id, delta, unit, reason) VALUES (?,?,?, 'production')",
              (batch_id, quantity, unit))

    # Ingrédients auto-ajoutés depuis la recette (1x rendement * facteur)
    if recipe_id:
        # Détermine facteur d'échelle (option simple: basé sur quantity vs yield_qty si dispo)
        factor = 1.0
        try:
            row = q(conn, "SELECT yield_qty FROM recipes WHERE id=?", (recipe_id,))
            recipe_yield = float(row[0][0]) if row and row[0][0] is not None else None
            if recipe_yield and recipe_yield > 0 and quantity and quantity > 0:
                factor = quantity / recipe_yield
        except Exception:
            factor = 1.0

        for ing in get_recipe_ingredients(conn, recipe_id):
            qty_used = round((ing["qty"] or 0) * factor, 4)
            c.execute(
                "INSERT INTO batch_inputs(batch_id, ingredient_id, qty_used, unit) VALUES (?,?,?,?)",
                (batch_id, ing["ingredient_id"], qty_used, ing["unit"])
            )

    conn.commit()
    return batch_id, lot_code


def record_ph(conn, batch_id: int, test_day: int, ph_value: Optional[float], notes: str = ""):
    today = dt.date.today().isoformat()
    result = "N/A"
    if ph_value is not None:
        # Règle par défaut; si product_targets existe pour ce lot, la surcharger
        result = "OK" if ph_value <= 4.6 else "À risque"
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO batch_tests(batch_id, test_type, test_day, value, result, notes, tested_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (batch_id, 'pH', test_day, ph_value, result, notes, today)
    )

    # Auto-statut à J14
    if test_day == 14:
        # Essaie de lire une cible spécifique
        target = q(conn, (
            "SELECT COALESCE(pt.ph_max, 4.6) FROM production_batches b "
            "LEFT JOIN product_targets pt ON (pt.recipe_id = b.recipe_id OR pt.product_id = b.product_id) "
            "WHERE b.batch_id = ? LIMIT 1"
        ), (batch_id,))
        ph_max = float(target[0][0]) if target and target[0][0] is not None else 4.6
        new_status = 'conforme' if (ph_value is not None and ph_value <= ph_max) else 'non_conforme'
        c.execute("UPDATE production_batches SET status=? WHERE batch_id=?", (new_status, batch_id))

    conn.commit()


def lots_due_for_day14(conn, window_low: int = 12, window_high: int = 16):
    return q(conn, (
        """
        SELECT b.batch_id, b.lot_code, b.produced_at, COALESCE(p.name, r.name, ''), b.quantity, b.unit
        FROM production_batches b
        LEFT JOIN products p ON p.id=b.product_id
        LEFT JOIN recipes r ON r.id=b.recipe_id
        WHERE b.status IN ('J0','J14')
          AND DATE(b.produced_at) BETWEEN DATE('now', ? || ' days') AND DATE('now', ? || ' days')
          AND NOT EXISTS (
            SELECT 1 FROM batch_tests t WHERE t.batch_id=b.batch_id AND t.test_type='pH' AND t.test_day=14
          )
        ORDER BY b.produced_at ASC
        """
    ), (-window_high, -window_low))


def consume_finished_stock(conn, batch_id: int, qty: float, unit: str, reason: str = 'vente'):
    c = conn.cursor()
    c.execute("INSERT INTO finished_inventory(batch_id, delta, unit, reason) VALUES (?,?,?,?)",
              (batch_id, -abs(qty), unit, reason))
    conn.commit()

# -------------------- UI --------------------

st.title("Registre de production – ACPOF")

TAB1, TAB2, TAB3 = st.tabs(["Produire", "Contrôles pH J14", "Lots & Stock"])

with TAB1:
    st.subheader("Créer un lot")
    with st.form("new_batch"):
        c1, c2, c3 = st.columns(3)
        production_type = c1.selectbox("Type", ["maison", "forfait"], index=0)
        client_id = None
        if production_type == 'forfait':
            client_opt = get_client_options(conn)
            client_label_to_id = {label: id for id, label in [(o[0], o[1]) for o in client_opt]}
            client_label = c2.selectbox("Client", [o[1] for o in client_opt])
            # retrouve id (peut être None)
            client_id = [o[0] for o in client_opt if o[1] == client_label][0]
        produced_at = c3.date_input("Date de fabrication", value=dt.date.today()).isoformat()

        rcol, pcol = st.columns(2)
        recipe_opt = get_recipe_options(conn)
        recipe_id = None
        if recipe_opt:
            recipe_label = rcol.selectbox("Recette (pour auto-ingrédients)", [o[1] for o in recipe_opt])
            recipe_id = [o[0] for o in recipe_opt if o[1] == recipe_label][0]
        else:
            rcol.info("Aucune recette trouvée.")
        product_opt = get_product_options(conn)
        product_id = None
        if product_opt:
            product_label = pcol.selectbox("Produit (SKU)", [o[1] for o in product_opt])
            product_id = [o[0] for o in product_opt if o[1] == product_label][0]

        c4, c5, c6 = st.columns(3)
        quantity = c4.number_input("Quantité produite", min_value=0.0, step=1.0)
        unit = c5.text_input("Unité (ex.: pot, kg)", value="pot")
        format_ = c6.text_input("Format (ex.: 250 ml)", value="")

        c7, c8 = st.columns(2)
        responsible = c7.text_input("Responsable", value="")
        notes = c8.text_input("Notes", value="")

        submitted = st.form_submit_button("Créer le lot")
        if submitted:
            if quantity <= 0:
                st.error("Veuillez saisir une quantité > 0.")
            else:
                batch_id, lot_code = create_batch(conn, produced_at, recipe_id, product_id,
                                                   production_type, client_id, quantity, unit,
                                                   format_, responsible, notes)
                st.success(f"Lot créé : {lot_code}")
                st.session_state["last_batch_id"] = batch_id
                st.session_state["last_lot_code"] = lot_code

    if st.session_state.get("last_batch_id"):
        st.divider()
        st.subheader("pH J0")
        ph0 = st.number_input("Valeur pH J0", min_value=0.0, step=0.01, key="ph0")
        ph0_notes = st.text_input("Notes J0", key="ph0_notes")
        if st.button("Enregistrer pH J0"):
            record_ph(conn, st.session_state["last_batch_id"], 0, ph0, ph0_notes)
            st.info("pH J0 enregistré.")

with TAB2:
    st.subheader("Lots à contrôler (J14)")
    rows = lots_due_for_day14(conn)
    if not rows:
        st.success("Aucun lot à contrôler dans la fenêtre J14 (D-16 à D-12).")
    else:
        for b_id, lot, prod_date, name, qty, u in rows:
            with st.expander(f"{lot} – {prod_date} – {name} – {qty} {u}"):
                c1, c2 = st.columns(2)
                ph14 = c1.number_input(f"pH J14 – {lot}", min_value=0.0, step=0.01, key=f"ph14_{b_id}")
                notes14 = c2.text_input("Notes", key=f"notes14_{b_id}")
                if st.button("Enregistrer J14", key=f"btn14_{b_id}"):
                    record_ph(conn, b_id, 14, ph14, notes14)
                    st.success("Mesure J14 enregistrée et statut mis à jour.")

with TAB3:
    st.subheader("Journal des lots")
    # Filtre simple
    c1, c2 = st.columns(2)
    date_min = c1.date_input("Date min", value=dt.date.today() - dt.timedelta(days=30))
    date_max = c2.date_input("Date max", value=dt.date.today())
    rows = q(conn, (
        """
        SELECT b.batch_id, b.lot_code, b.produced_at, COALESCE(p.name, r.name, ''), b.production_type,
               b.quantity, b.unit, b.status
        FROM production_batches b
        LEFT JOIN products p ON p.id = b.product_id
        LEFT JOIN recipes r  ON r.id = b.recipe_id
        WHERE DATE(b.produced_at) BETWEEN ? AND ?
        ORDER BY b.produced_at DESC, b.lot_code DESC
        """
    ), (date_min.isoformat(), date_max.isoformat()))

    if rows:
        for (b_id, lot, dte, name, typ, qty, u, stt) in rows:
            with st.expander(f"{lot} – {dte} – {name} – {qty} {u} – {typ} – {stt}"):
                st.caption("Ingrédients (quantités calculées)")
                inputs = q(conn, (
                    "SELECT i.name, bi.qty_used, bi.unit FROM batch_inputs bi "
                    "JOIN ingredients i ON i.id = bi.ingredient_id "
                    "WHERE bi.batch_id = ? ORDER BY i.name"
                ), (b_id,))
                if inputs:
                    st.table([{"Ingrédient": r[0], "Quantité": r[1], "Unité": r[2]} for r in inputs])
                else:
                    st.write("—")

                st.caption("Tests enregistrés")
                tests = q(conn, (
                    "SELECT test_type, test_day, value, result, tested_at, COALESCE(notes,'') FROM batch_tests WHERE batch_id=? ORDER BY tested_at"
                ), (b_id,))
                if tests:
                    st.table([
                        {"Type": t[0], "Jour": t[1], "Valeur": t[2], "Résultat": t[3], "Date": t[4], "Notes": t[5]}
                        for t in tests
                    ])
                else:
                    st.write("—")

                st.caption("Mouvements d'inventaire (lot)")
                moves = q(conn, (
                    "SELECT delta, unit, reason, at FROM finished_inventory WHERE batch_id=? ORDER BY at"
                ), (b_id,))
                if moves:
                    st.table([{"Delta": m[0], "Unité": m[1], "Raison": m[2], "Quand": m[3]} for m in moves])
                else:
                    st.write("—")

                st.divider()
                c1, c2, c3 = st.columns(3)
                qty_out = c1.number_input(f"Sortie de stock ({lot})", min_value=0.0, step=1.0, key=f"out_{b_id}")
                reason = c2.selectbox("Raison", ["vente","rebut","don","ajustement"], key=f"reason_{b_id}")
                if c3.button("Enregistrer sortie", key=f"btn_out_{b_id}"):
                    if qty_out > 0:
                        consume_finished_stock(conn, b_id, qty_out, u, reason)
                        st.success("Sortie enregistrée.")
                    else:
                        st.error("Quantité doit être > 0.")

# --------------------------------------------------------------
# FIN DU FICHIER
# --------------------------------------------------------------
