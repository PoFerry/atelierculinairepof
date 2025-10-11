from __future__ import annotations

import streamlit as st
from pathlib import Path

from db import init_db, SessionLocal
from acpof_pages.ingredients import ingredients_page
from acpof_pages.recipes import recipes_page
from acpof_pages.menus import menus_page
from acpof_pages.suppliers import suppliers_page
from acpof_pages.inventory import inventory_page

st.set_page_config(page_title="Atelier Culinaire POF", page_icon="🍽️", layout="wide")

APP_DIR = Path(__file__).parent
LOGO_PATHS = [APP_DIR/"Logo_atelierPOF.png", APP_DIR/"logo_atelierpof.png", APP_DIR/"assets/Logo_atelierPOF.png"]

def _logo_path():
    for p in LOGO_PATHS:
        if p.exists():
            return str(p)
    return None

# ——— styles (sidebar + top header) ———
st.markdown("""
<style>
/* Top header */
.acpof-topbar {
  background: linear-gradient(90deg,#111827,#1f2937);
  color: #e5e7eb;
  padding: 14px 18px;
  border-radius: 12px;
  margin: 6px 0 16px 0;
  display:flex; align-items:center; gap:12px;
  border: 1px solid rgba(255,255,255,0.06);
}
.acpof-topbar .title {
  font-weight: 700; letter-spacing:.3px; font-size: 1.05rem;
}
section[data-testid="stSidebar"] { background:#0f172a; color:#e5e7eb; }
section[data-testid="stSidebar"] * { color:#e5e7eb; }
div[role="radiogroup"] > label {
  padding: 10px 12px; border-radius: 10px; margin-bottom: 6px;
  border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);
}
div[role="radiogroup"] > label:hover { border-color: rgba(255,255,255,0.25); background: rgba(255,255,255,0.06); }
.sidebar-title { font-weight:700; letter-spacing:.3px; font-size:.9rem; color:#cbd5e1; margin:6px 0 4px 0; }
.badge { display:inline-block; padding:2px 8px; border-radius:9999px; background:#1e293b; color:#cbd5e1; font-size:12px; border:1px solid rgba(255,255,255,0.08); margin-left:8px; }
</style>
""", unsafe_allow_html=True)

def page_header():
    logo = _logo_path()
    if logo:
        st.markdown(f"""
        <div class="acpof-topbar">
          <img src="app://{logo}" style="height:28px;border-radius:6px;" />
          <div class="title">Outils de gestion ACPOF</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown('<div class="acpof-topbar"><div class="title">Outils de gestion ACPOF</div></div>', unsafe_allow_html=True)

def sidebar_nav(db):
    # petites métriques pour badges
    from db import Ingredient, Recipe, Menu
    ing_n = db.query(Ingredient).count()
    rec_n = db.query(Recipe).count()
    menu_n = db.query(Menu).count()

    st.sidebar.markdown('<div class="sidebar-title">Navigation</div>', unsafe_allow_html=True)
    options = {
        f"🧂 Ingrédients  <span class='badge'>{ing_n}</span>": ingredients_page,
        f"📖 Recettes  <span class='badge'>{rec_n}</span>": recipes_page,
        f"🗂️ Menus  <span class='badge'>{menu_n}</span>": menus_page,
        "🏷️ Fournisseurs": suppliers_page,
        "📦 Inventaire": inventory_page,
    }
    choice = st.sidebar.radio("", list(options.keys()), index=0, key="acpof_nav")
    st.sidebar.markdown("---")
    st.sidebar.caption("Atelier Culinaire Pierre-Olivier Ferry")
    return options[choice]

def main():
    init_db()
    db = SessionLocal()
    # Header commun sur chaque page :
    page_header()
    # Navigation custom (plus de doublons)
    page_fn = sidebar_nav(db)
    # Afficher la page choisie
    page_fn(db)

if __name__ == "__main__":
    main()
